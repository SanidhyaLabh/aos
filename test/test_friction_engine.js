import { ethers } from "ethers";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const artifactsDir = path.join(rootDir, "artifacts");

// ANSI terminal colors
const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const CYAN = "\x1b[36m";
const YELLOW = "\x1b[33m";

async function runTests() {
  console.log(`\n${BOLD}========================================================================${RESET}`);
  console.log(`${BOLD}   DUAL-HORIZON FRICTION ENGINE (DHFE) — ON-CHAIN VERIFICATION SUITE   ${RESET}`);
  console.log(`${BOLD}========================================================================${RESET}\n`);

  const rpcUrl = process.env.RPC_URL || "http://127.0.0.1:8545";
  const provider = new ethers.JsonRpcProvider(rpcUrl);

  const deployer = await provider.getSigner(0);
  const user = await provider.getSigner(3);
  const attacker = await provider.getSigner(4);

  const frictionArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "FrictionEngine.json"), "utf8"));
  const lendingArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ToyLendingMarket.json"), "utf8"));
  const asoArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ASOAdapter.json"), "utf8"));

  // 1. Deploy FrictionEngine
  const FrictionFactory = new ethers.ContractFactory(frictionArtifact.abi, frictionArtifact.bytecode, deployer);
  const engine = await FrictionFactory.deploy();
  await engine.waitForDeployment();
  const engineAddress = await engine.getAddress();

  await (await engine.setFallbackGamma(ethers.parseEther("400000"))).wait(); // Gamma = $400k
  // lambda = 0.95, k_phi = 3, beta = 1.5, nActive = 50
  await (await engine.setParameters(
    ethers.parseEther("0.95"),
    3,
    ethers.parseEther("1.5"),
    50
  )).wait();

  // Test 1: Single small borrow -> near-zero friction
  console.log(`${CYAN}[TEST 1/4] Scenario: Honest User Small Borrow ($2,000)${RESET}`);
  const [fInst1, fCum1, fFinal1] = await engine.computeFriction(await user.getAddress(), ethers.parseEther("2000"));
  const fInstNum = Number(ethers.formatEther(fInst1));
  const fCumNum = Number(ethers.formatEther(fCum1));
  const fFinalNum = Number(ethers.formatEther(fFinal1));
  const effRate1 = await engine.effectiveRate(ethers.parseEther("0.05"), fFinal1);
  const effRateNum = Number(ethers.formatEther(effRate1));

  console.log(`  f_inst:         ${fInstNum.toFixed(6)}`);
  console.log(`  f_cum:          ${fCumNum.toFixed(6)}`);
  console.log(`  f_final:        ${fFinalNum.toFixed(6)}`);
  console.log(`  effective_rate: ${(effRateNum * 100).toFixed(4)}% (Base: 5.0000%)`);

  if (fInstNum > 0.0001 || fFinalNum > 0.001) {
    throw new Error(`Test 1 Failed: small borrow friction too high: ${fFinalNum}`);
  }
  console.log(`  ${GREEN}✓ TEST 1 PASSED: Small borrow incurs virtually zero friction.${RESET}\n`);

  // Test 2: Single large borrow near Gamma-D -> high f_inst
  console.log(`${CYAN}[TEST 2/4] Scenario: One-Shot Large Borrow ($250,000 near $400k Gamma)${RESET}`);
  const [fInst2, fCum2, fFinal2] = await engine.computeFriction(await attacker.getAddress(), ethers.parseEther("250000"));
  const fInstNum2 = Number(ethers.formatEther(fInst2));
  const fFinalNum2 = Number(ethers.formatEther(fFinal2));
  const effRate2 = await engine.effectiveRate(ethers.parseEther("0.05"), fFinal2);
  const effRateNum2 = Number(ethers.formatEther(effRate2));

  console.log(`  f_inst:         ${fInstNum2.toFixed(6)}`);
  console.log(`  f_final:        ${fFinalNum2.toFixed(6)}`);
  console.log(`  effective_rate: ${(effRateNum2 * 100).toFixed(4)}% (Spike to 12.5%)`);

  if (fInstNum2 < 0.2 || fFinalNum2 < 0.5) {
    throw new Error(`Test 2 Failed: large borrow did not produce high instantaneous friction`);
  }
  console.log(`  ${GREEN}✓ TEST 2 PASSED: One-shot large borrow triggered high f_inst & rate spike.${RESET}\n`);

  // Test 3: Structuring Resistance: 10 small borrows in sequence
  console.log(`${CYAN}[TEST 3/4] Scenario: Structuring-Resistance (10x $10k Borrows Sequence)${RESET}`);
  const structuredAttacker = await attacker.getAddress();
  let prevFCum = 0;
  let prevFFinal = 0;

  for (let i = 1; i <= 10; i++) {
    const [fInstSlice, fCumSlice, fFinalSlice] = await engine.computeFriction(structuredAttacker, ethers.parseEther("10000"));
    const curFCum = Number(ethers.formatEther(fCumSlice));
    const curFFinal = Number(ethers.formatEther(fFinalSlice));
    const curFInst = Number(ethers.formatEther(fInstSlice));

    // Each individual slice is small ($10k / $400k = 2.5%), so f_inst remains near-zero
    if (curFInst > 0.0001) {
      throw new Error(`Slice f_inst unexpectedly high: ${curFInst}`);
    }

    // Cumulative friction f_cum must rise monotonically
    if (i > 1 && curFCum <= prevFCum) {
      throw new Error(`Structuring resistance violated: f_cum did not rise at slice #${i}`);
    }

    prevFCum = curFCum;
    prevFFinal = curFFinal;

    // Update on-chain exposure
    await (await engine.updateExposure(structuredAttacker, ethers.parseEther("10000"))).wait();
    console.log(`  Slice #${i.toString().padStart(2, ' ')}: f_inst=${curFInst.toFixed(6)} | f_cum=${curFCum.toFixed(6)} | f_final=${curFFinal.toFixed(6)}`);
  }

  if (prevFCum < 0.05) {
    throw new Error(`Test 3 Failed: cumulative friction after 10 slices too low: ${prevFCum}`);
  }
  console.log(`  ${GREEN}✓ TEST 3 PASSED: Structuring-resistance verified — f_cum climbs steadily while each f_inst stays low.${RESET}\n`);

  // Test 4: Full on-chain ToyLendingMarket integration & FrictionApplied event emission
  console.log(`${CYAN}[TEST 4/4] Scenario: ToyLendingMarket End-to-End Borrow + Event Subscription${RESET}`);
  const AsoFactory = new ethers.ContractFactory(asoArtifact.abi, asoArtifact.bytecode, deployer);
  const aso = await AsoFactory.deploy(ethers.parseEther("100"));
  await aso.waitForDeployment();
  await (await aso.connect(deployer).depositBond({ value: ethers.parseEther("1.0") })).wait();

  const LendingFactory = new ethers.ContractFactory(lendingArtifact.abi, lendingArtifact.bytecode, deployer);
  const lending = await LendingFactory.deploy(await aso.getAddress(), "ASOAdapter");
  await lending.waitForDeployment();

  // Wire FrictionEngine into ToyLendingMarket
  await (await lending.setFrictionEngine(engineAddress)).wait();
  await (await engine.setLendingMarket(await lending.getAddress())).wait();

  // Deposit collateral for user
  await (await lending.connect(user).depositCollateral(ethers.parseEther("1000"))).wait();

  // Execute borrow and capture FrictionApplied event
  const tx = await lending.connect(user).borrow(ethers.parseEther("10000"));
  const receipt = await tx.wait();

  // Find FrictionApplied event
  let frictionEventFound = false;
  for (const log of receipt.logs) {
    try {
      const parsed = lending.interface.parseLog(log);
      if (parsed && parsed.name === "FrictionApplied") {
        frictionEventFound = true;
        console.log(`  On-Chain Event Emitted: FrictionApplied(`);
        console.log(`    user:          ${parsed.args.user}`);
        console.log(`    fInst:         ${ethers.formatEther(parsed.args.fInst)}`);
        console.log(`    fCum:          ${ethers.formatEther(parsed.args.fCum)}`);
        console.log(`    fFinal:        ${ethers.formatEther(parsed.args.fFinal)}`);
        console.log(`    effectiveRate: ${(Number(ethers.formatEther(parsed.args.effectiveRate)) * 100).toFixed(4)}%`);
        console.log(`  )`);
      }
    } catch (_) {}
  }

  if (!frictionEventFound) {
    throw new Error("Test 4 Failed: FrictionApplied event not emitted by ToyLendingMarket");
  }
  console.log(`  ${GREEN}✓ TEST 4 PASSED: ToyLendingMarket correctly evaluated friction and emitted FrictionApplied event.${RESET}\n`);

  console.log(`${BOLD}========================================================================${RESET}`);
  console.log(`${GREEN}${BOLD}ALL 4 DHFE TESTS PASSED (100% SUCCESS)${RESET}`);
  console.log(`${BOLD}========================================================================${RESET}\n`);
}

runTests().catch((err) => {
  console.error(`\n${RED}[TEST FAILED]${RESET}`, err);
  process.exit(1);
});
