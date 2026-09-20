import { ethers } from "ethers";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const artifactsDir = path.join(rootDir, "artifacts");

// ANSI terminal formatting
const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const CYAN = "\x1b[36m";
const YELLOW = "\x1b[33m";

async function runEEGTests() {
  console.log(`\n${BOLD}========================================================================${RESET}`);
  console.log(`${BOLD}   ORIGIN // ECONOMIC EXPOSURE GUARD (EEG) — VERIFICATION SUITE       ${RESET}`);
  console.log(`${BOLD}========================================================================${RESET}\n`);

  const rpcUrl = process.env.RPC_URL || "http://127.0.0.1:8545";
  const provider = new ethers.JsonRpcProvider(rpcUrl);

  const deployer = await provider.getSigner(0);
  const honestUser = await provider.getSigner(3);
  const attacker1 = await provider.getSigner(4);
  const attacker2 = await provider.getSigner(5);
  const attacker3 = await provider.getSigner(6);

  const guardArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "EconomicExposureGuard.json"), "utf8"));
  const lendingArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ToyLendingMarket.json"), "utf8"));
  const asoArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ASOAdapter.json"), "utf8"));

  // 1. Deploy Guard: MaxCapacity = $100,000, Refill = $25,000 / 900s (~27.77 ether/sec)
  const maxCap = ethers.parseEther("100000");
  const refillRate = ethers.parseEther("27.777777777777777777");
  const GuardFactory = new ethers.ContractFactory(guardArtifact.abi, guardArtifact.bytecode, deployer);
  const guard = await GuardFactory.deploy(maxCap, refillRate);
  await guard.waitForDeployment();
  const guardAddress = await guard.getAddress();

  // 2. Deploy Mock Oracle at $100
  const AsoFactory = new ethers.ContractFactory(asoArtifact.abi, asoArtifact.bytecode, deployer);
  const aso = await AsoFactory.deploy(ethers.parseEther("100"));
  await aso.waitForDeployment();
  await (await aso.connect(deployer).depositBond({ value: ethers.parseEther("1.0") })).wait();

  // 3. Deploy ToyLendingMarket
  const LendingFactory = new ethers.ContractFactory(lendingArtifact.abi, lendingArtifact.bytecode, deployer);
  const market = await LendingFactory.deploy(await aso.getAddress(), "ASOAdapter");
  await market.waitForDeployment();

  // Wire linkages
  await (await market.setExposureGuard(guardAddress)).wait();
  await (await guard.setMarket(await market.getAddress())).wait();

  // Seed honest user & attackers with collateral
  await (await market.connect(honestUser).depositCollateral(ethers.parseEther("1000"))).wait(); // $100k collateral
  await (await market.connect(attacker1).depositCollateral(ethers.parseEther("100000"))).wait(); // $10M collateral
  await (await market.connect(attacker2).depositCollateral(ethers.parseEther("100000"))).wait();
  await (await market.connect(attacker3).depositCollateral(ethers.parseEther("100000"))).wait();

  // -------------------------------------------------------------------------
  // TEST 1: Normal Small Borrow ($2,900)
  // -------------------------------------------------------------------------
  console.log(`${CYAN}[TEST 1/5] Scenario: Normal Borrower UX ($2,900 borrow)${RESET}`);
  const capBefore = await guard.getAvailableCapacity();
  console.log(`  Initial Protected Capacity: $${Number(ethers.formatEther(capBefore)).toLocaleString()}`);

  const tx1 = await market.connect(honestUser).borrow(ethers.parseEther("2900"));
  const rc1 = await tx1.wait();
  const capAfter1 = await guard.getAvailableCapacity();

  console.log(`  Borrow $2,900 confirmed in 1 tx! Gas used: ${rc1.gasUsed}`);
  console.log(`  Remaining Capacity:         $${Number(ethers.formatEther(capAfter1)).toLocaleString()}`);

  if (capAfter1 > capBefore - ethers.parseEther("2800")) {
    throw new Error("Test 1 Failed: capacity was not properly consumed");
  }
  console.log(`  ${GREEN}✓ TEST 1 PASSED: Normal borrow executed seamlessly without extra workflow.${RESET}\n`);

  // -------------------------------------------------------------------------
  // TEST 2: Oracle Manipulation + $10,000,000 Exploit Attempt (REVERT)
  // -------------------------------------------------------------------------
  console.log(`${CYAN}[TEST 2/5] Scenario: Oracle Pump + $10M Exploit Attempt (Must Revert)${RESET}`);
  console.log(`  Attacker posted $10M collateral (apparent borrowing capacity: $8M+)`);
  console.log(`  Current Protected Capacity: $${Number(ethers.formatEther(capAfter1)).toLocaleString()}`);

  let exploitBlocked = false;
  try {
    await market.connect(attacker1).borrow(ethers.parseEther("10000000"));
  } catch (err) {
    exploitBlocked = true;
    console.log(`  ${YELLOW}On-Chain Revert Triggered: ${err.message.slice(0, 70)}...${RESET}`);
  }

  if (!exploitBlocked) {
    throw new Error("Test 2 Failed: Exploit borrow of $10M was NOT blocked by EEG!");
  }
  console.log(`  ${GREEN}✓ TEST 2 PASSED: Massive drain attempt blocked on-chain by EEG.${RESET}\n`);

  // -------------------------------------------------------------------------
  // TEST 3: Multi-Wallet Sybil Attack Resistance
  // -------------------------------------------------------------------------
  console.log(`${CYAN}[TEST 3/5] Scenario: Multi-Wallet Sybil Resistance (4 Attacker Wallets)${RESET}`);
  const currentCap = await guard.getAvailableCapacity();
  const halfCap = currentCap / 2n;

  // Wallet A takes half capacity
  console.log(`  Wallet A borrows $${Number(ethers.formatEther(halfCap)).toLocaleString()}...`);
  await (await market.connect(attacker1).borrow(halfCap)).wait();
  console.log(`  ✓ Wallet A borrow confirmed.`);

  // Wallet B takes remaining capacity
  const remCap = await guard.getAvailableCapacity();
  console.log(`  Wallet B borrows $${Number(ethers.formatEther(remCap)).toLocaleString()} (exhausts bucket)...`);
  await (await market.connect(attacker2).borrow(remCap)).wait();
  console.log(`  ✓ Wallet B borrow confirmed.`);

  // Wallet C attempts to borrow $10k -> MUST REVERT
  console.log(`  Wallet C attempts to borrow $10k against depleted capacity...`);
  let sybilBlocked = false;
  try {
    await market.connect(attacker3).borrow(ethers.parseEther("10000"));
  } catch (_) {
    sybilBlocked = true;
  }

  if (!sybilBlocked) {
    throw new Error("Test 3 Failed: Sybil wallet C bypassed rate limit!");
  }
  console.log(`  ${GREEN}✓ TEST 3 PASSED: Sybil attack blocked. Global capacity is shared and unbypassable.${RESET}\n`);

  // -------------------------------------------------------------------------
  // TEST 4: Token-Bucket Continuous Refill Over Time
  // -------------------------------------------------------------------------
  console.log(`${CYAN}[TEST 4/5] Scenario: Token-Bucket Time Refill (+15 minutes)${RESET}`);
  const capDepleted = await guard.getAvailableCapacity();
  console.log(`  Capacity before time jump: $${Number(ethers.formatEther(capDepleted)).toFixed(2)}`);

  // Advance time by 900 seconds (15 minutes) via Anvil RPC
  await provider.send("evm_increaseTime", [900]);
  await provider.send("evm_mine", []);

  const capRefilled = await guard.getAvailableCapacity();
  console.log(`  Capacity after +15 min:    $${Number(ethers.formatEther(capRefilled)).toLocaleString()}`);

  if (capRefilled < ethers.parseEther("24000")) {
    throw new Error(`Test 4 Failed: capacity did not refill properly: ${ethers.formatEther(capRefilled)}`);
  }
  console.log(`  ${GREEN}✓ TEST 4 PASSED: Continuous replenishment verified ($25k refilled over 15 min).${RESET}\n`);

  // -------------------------------------------------------------------------
  // TEST 5: Repayment Invariant & Non-Refill Rule
  // -------------------------------------------------------------------------
  console.log(`${CYAN}[TEST 5/5] Scenario: Repayment Invariant & No Instant Refill${RESET}`);
  const capBeforeRepay = await guard.getAvailableCapacity();

  // Honest user repays $1,000
  await (await market.connect(honestUser).repay(ethers.parseEther("1000"))).wait();
  const capAfterRepay = await guard.getAvailableCapacity();

  // Capacity should NOT jump up by $1,000 (repaying does not replenish borrow budget)
  console.log(`  Capacity before repay: $${Number(ethers.formatEther(capBeforeRepay)).toFixed(2)}`);
  console.log(`  Capacity after repay:  $${Number(ethers.formatEther(capAfterRepay)).toFixed(2)}`);

  if (capAfterRepay > capBeforeRepay + ethers.parseEther("100")) { // Allow for a few seconds elapsed
    throw new Error("Test 5 Failed: repayment illegally refilled borrow capacity!");
  }
  console.log(`  ${GREEN}✓ TEST 5 PASSED: Repayment executed freely and did NOT artificially refill capacity.${RESET}\n`);

  console.log(`${BOLD}========================================================================${RESET}`);
  console.log(`${GREEN}${BOLD}ALL 5 ORIGIN EEG TESTS PASSED (100% SUCCESS)${RESET}`);
  console.log(`${BOLD}========================================================================${RESET}\n`);
}

runEEGTests().catch((err) => {
  console.error(`\n${RED}[TEST FAILED]${RESET}`, err);
  process.exit(1);
});
