import { ethers } from "ethers";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");
const artifactsDir = path.join(rootDir, "artifacts");

const RESET = "\x1b[0m";
const BOLD = "\x1b[1m";
const GREEN = "\x1b[32m";
const RED = "\x1b[31m";
const CYAN = "\x1b[36m";
const YELLOW = "\x1b[33m";

async function runEIP712Tests() {
  console.log(`\n${BOLD}========================================================================${RESET}`);
  console.log(`${BOLD}   ORIGIN // EIP-712 ATTESTATION & CRYPTOGRAPHIC VERIFICATION SUITE    ${RESET}`);
  console.log(`${BOLD}========================================================================${RESET}\n`);

  const rpcUrl = process.env.RPC_URL || "http://127.0.0.1:8545";
  const provider = new ethers.JsonRpcProvider(rpcUrl);

  const deployer = await provider.getSigner(0);
  const attester = await provider.getSigner(1); // Whitelisted bonded attester
  const rogueAttester = await provider.getSigner(9); // Unbonded attacker

  const asoArtifact = JSON.parse(fs.readFileSync(path.join(artifactsDir, "ASOAdapter.json"), "utf8"));

  // Deploy ASOAdapter
  const AsoFactory = new ethers.ContractFactory(asoArtifact.abi, asoArtifact.bytecode, deployer);
  const aso = await AsoFactory.deploy(ethers.parseEther("100"));
  await aso.waitForDeployment();
  const asoAddr = await aso.getAddress();
  const network = await provider.getNetwork();
  const chainId = network.chainId;

  console.log(`  ASOAdapter deployed at: ${asoAddr}, ChainId: ${chainId}`);

  // Attester deposits 1.0 ETH bond to become whitelisted
  await (await aso.connect(attester).depositBond({ value: ethers.parseEther("1.0") })).wait();
  console.log(`  Attester deposited 1.0 ETH bond. Whitelisted: true`);

  const domain = {
    name: "ORIGIN ASO",
    version: "1",
    chainId: chainId,
    verifyingContract: asoAddr
  };

  const types = {
    Observation: [
      { name: "sourceId", type: "bytes32" },
      { name: "sourceGroup", type: "bytes32" },
      { name: "price", type: "uint256" },
      { name: "timestamp", type: "uint256" }
    ],
    Attestation: [
      { name: "assetId", type: "bytes32" },
      { name: "aggregatePrice", type: "uint256" },
      { name: "observations", type: "Observation[]" },
      { name: "windowStart", type: "uint256" },
      { name: "windowEnd", type: "uint256" },
      { name: "roundId", type: "uint256" },
      { name: "validUntil", type: "uint256" }
    ]
  };

  const assetId = ethers.keccak256(ethers.toUtf8Bytes("RWAUSD"));
  const group1 = ethers.keccak256(ethers.toUtf8Bytes("GROUP_CUSTODIAN"));
  const group2 = ethers.keccak256(ethers.toUtf8Bytes("GROUP_EXCHANGE"));
  const group3 = ethers.keccak256(ethers.toUtf8Bytes("GROUP_INTERBANK"));

  const src1 = ethers.keccak256(ethers.toUtf8Bytes("Ondo"));
  const src2 = ethers.keccak256(ethers.toUtf8Bytes("Coinbase"));
  const src3 = ethers.keccak256(ethers.toUtf8Bytes("Kraken"));

  // -------------------------------------------------------------------------
  // TEST 1: Valid EIP-712 Attestation Submission
  // -------------------------------------------------------------------------
  console.log(`\n${CYAN}[TEST 1/6] Valid EIP-712 Attestation Acceptance${RESET}`);
  const block = await provider.getBlock("latest");
  const now = block.timestamp;

  const validAttestation = {
    assetId: assetId,
    aggregatePrice: ethers.parseEther("100.02"),
    observations: [
      { sourceId: src1, sourceGroup: group1, price: ethers.parseEther("100.01"), timestamp: now },
      { sourceId: src2, sourceGroup: group2, price: ethers.parseEther("100.02"), timestamp: now },
      { sourceId: src3, sourceGroup: group3, price: ethers.parseEther("100.03"), timestamp: now }
    ],
    windowStart: now - 10,
    windowEnd: now,
    roundId: 1,
    validUntil: now + 3600
  };

  const signature = await attester.signTypedData(domain, types, validAttestation);

  const payload = {
    ...validAttestation,
    signature: signature
  };

  const tx1 = await aso.connect(attester).submitAttestation(payload);
  await tx1.wait();

  const [price1, , status1] = await aso.getPrice(assetId);
  console.log(`  Price Accepted: $${ethers.formatEther(price1)}, Status: ${status1} (FRESH=0)`);
  if (price1 !== ethers.parseEther("100.02")) {
    throw new Error("Test 1 Failed: Price not set to aggregate price");
  }
  console.log(`  ${GREEN}✓ TEST 1 PASSED: Valid EIP-712 attestation accepted on-chain.${RESET}`);

  // -------------------------------------------------------------------------
  // TEST 2: Replay Attack Rejection (Same Round ID)
  // -------------------------------------------------------------------------
  console.log(`\n${CYAN}[TEST 2/6] Replay Attack Prevention (Same Round ID)${RESET}`);
  let replayBlocked = false;
  try {
    const tx = await aso.connect(attester).submitAttestation(payload);
    await tx.wait();
  } catch (err) {
    replayBlocked = true;
    console.log(`  Replay blocked on-chain as expected.`);
  }
  if (!replayBlocked) throw new Error("Test 2 Failed: Replay attack was not blocked!");
  console.log(`  ${GREEN}✓ TEST 2 PASSED: Replay attack rejected by monotonic round check.${RESET}`);

  // -------------------------------------------------------------------------
  // TEST 3: Out-of-Band Divergence Rejection (> 50 bps)
  // -------------------------------------------------------------------------
  console.log(`\n${CYAN}[TEST 3/6] Excessive Source Divergence (> 50 bps) Rejection${RESET}`);
  const block3 = await provider.getBlock("latest");
  const now3 = block3.timestamp;

  const divergentAttestation = {
    assetId: assetId,
    aggregatePrice: ethers.parseEther("100.00"),
    observations: [
      { sourceId: src1, sourceGroup: group1, price: ethers.parseEther("99.00"), timestamp: now3 },  // -1.0%
      { sourceId: src2, sourceGroup: group2, price: ethers.parseEther("100.00"), timestamp: now3 },
      { sourceId: src3, sourceGroup: group3, price: ethers.parseEther("101.00"), timestamp: now3 }  // +1.0% (200 bps spread)
    ],
    windowStart: now3 - 10,
    windowEnd: now3,
    roundId: 2,
    validUntil: now3 + 3600
  };

  const sig3 = await attester.signTypedData(domain, types, divergentAttestation);
  let divergenceBlocked = false;
  try {
    const tx = await aso.connect(attester).submitAttestation({ ...divergentAttestation, signature: sig3 });
    await tx.wait();
  } catch (err) {
    divergenceBlocked = true;
    console.log(`  Divergence 200 bps rejected on-chain (max allowed: 50 bps).`);
  }
  if (!divergenceBlocked) throw new Error("Test 3 Failed: Divergence was not rejected");
  console.log(`  ${GREEN}✓ TEST 3 PASSED: Out-of-band divergence rejected on-chain.${RESET}`);

  // -------------------------------------------------------------------------
  // TEST 4: Dependent Source Group Rejection (< 2 independent groups)
  // -------------------------------------------------------------------------
  console.log(`\n${CYAN}[TEST 4/6] Dependent Source Group Rejection (Sybil Sources)${RESET}`);
  const block4 = await provider.getBlock("latest");
  const now4 = block4.timestamp;

  const dependentAttestation = {
    assetId: assetId,
    aggregatePrice: ethers.parseEther("100.02"),
    observations: [
      { sourceId: src1, sourceGroup: group1, price: ethers.parseEther("100.01"), timestamp: now4 },
      { sourceId: src2, sourceGroup: group1, price: ethers.parseEther("100.02"), timestamp: now4 },
      { sourceId: src3, sourceGroup: group1, price: ethers.parseEther("100.03"), timestamp: now4 }
    ],
    windowStart: now4 - 10,
    windowEnd: now4,
    roundId: 3,
    validUntil: now4 + 3600
  };

  const sig4 = await attester.signTypedData(domain, types, dependentAttestation);
  let dependentBlocked = false;
  try {
    const tx = await aso.connect(attester).submitAttestation({ ...dependentAttestation, signature: sig4 });
    await tx.wait();
  } catch (err) {
    dependentBlocked = true;
    console.log(`  Dependent sources rejected: only 1 independent group present.`);
  }
  if (!dependentBlocked) throw new Error("Test 4 Failed: Dependent sources were not rejected");
  console.log(`  ${GREEN}✓ TEST 4 PASSED: Sybil / dependent sources rejected on-chain.${RESET}`);

  // -------------------------------------------------------------------------
  // TEST 5: Insufficient Quorum Rejection (< 3 sources)
  // -------------------------------------------------------------------------
  console.log(`\n${CYAN}[TEST 5/6] Insufficient Quorum Rejection (< 3 sources)${RESET}`);
  const block5 = await provider.getBlock("latest");
  const now5 = block5.timestamp;

  const quorumAttestation = {
    assetId: assetId,
    aggregatePrice: ethers.parseEther("100.02"),
    observations: [
      { sourceId: src1, sourceGroup: group1, price: ethers.parseEther("100.01"), timestamp: now5 },
      { sourceId: src2, sourceGroup: group2, price: ethers.parseEther("100.02"), timestamp: now5 }
    ],
    windowStart: now5 - 10,
    windowEnd: now5,
    roundId: 4,
    validUntil: now5 + 3600
  };

  const sig5 = await attester.signTypedData(domain, types, quorumAttestation);
  let quorumBlocked = false;
  try {
    const tx = await aso.connect(attester).submitAttestation({ ...quorumAttestation, signature: sig5 });
    await tx.wait();
  } catch (err) {
    quorumBlocked = true;
    console.log(`  Quorum of 2 rejected: minimum 3 required.`);
  }
  if (!quorumBlocked) throw new Error("Test 5 Failed: Quorum < 3 was not rejected");
  console.log(`  ${GREEN}✓ TEST 5 PASSED: Insufficient quorum rejected on-chain.${RESET}`);

  // -------------------------------------------------------------------------
  // TEST 6: Unauthorized / Unbonded Attester Signature Rejection
  // -------------------------------------------------------------------------
  console.log(`\n${CYAN}[TEST 6/6] Unauthorized / Unbonded Attester Rejection${RESET}`);
  const block6 = await provider.getBlock("latest");
  const now6 = block6.timestamp;

  const rogueAttestation = {
    assetId: assetId,
    aggregatePrice: ethers.parseEther("100.02"),
    observations: [
      { sourceId: src1, sourceGroup: group1, price: ethers.parseEther("100.01"), timestamp: now6 },
      { sourceId: src2, sourceGroup: group2, price: ethers.parseEther("100.02"), timestamp: now6 },
      { sourceId: src3, sourceGroup: group3, price: ethers.parseEther("100.03"), timestamp: now6 }
    ],
    windowStart: now6 - 10,
    windowEnd: now6,
    roundId: 5,
    validUntil: now6 + 3600
  };

  const sig6 = await rogueAttester.signTypedData(domain, types, rogueAttestation);
  let rogueBlocked = false;
  try {
    const tx = await aso.connect(rogueAttester).submitAttestation({ ...rogueAttestation, signature: sig6 });
    await tx.wait();
  } catch (err) {
    rogueBlocked = true;
    console.log(`  Unbonded attacker signature rejected.`);
  }
  if (!rogueBlocked) throw new Error("Test 6 Failed: Rogue attester was not rejected");
  console.log(`  ${GREEN}✓ TEST 6 PASSED: Unauthorized attester rejected on-chain.${RESET}`);

  console.log(`\n========================================================================`);
  console.log(`ALL 6 EIP-712 ATTESTATION INVARIANTS VERIFIED (100% SUCCESS)`);
  console.log(`========================================================================\n`);
}

runEIP712Tests().catch((err) => {
  console.error(`${RED}[TEST FAILED]${RESET}`, err);
  process.exit(1);
});
