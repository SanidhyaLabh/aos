// SPDX-License-Identifier: MIT
/**
 * @file liveAttestationService.js (Origin // ASO v2)
 * @notice Unattended backend pipeline implementing:
 * 1. Cryptographic ASO Attestation (EIP-191 signatures + Anvil submission)
 * 2. Quantitative Risk Engine (Liquidity-weighted median, TWAP, price velocity)
 * 3. Manipulation Cost vs Extractable Value Gate
 * 4. Weakest Link Source Ranking
 * 5. Vault Integrity Sanity Checking (Venus defense)
 * 6. Sentinel Registry 6-State Machine Synchronization
 */

import { ethers } from "ethers";
import express from "express";
import cors from "cors";
import fs from "fs";
import path from "path";
import { fileURLToPath } from "url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const rootDir = path.resolve(__dirname, "..");

// Load deployment details
const deployPath = path.join(rootDir, "src", "deployments.json");
if (!fs.existsSync(deployPath)) {
  console.error(`[AttestationService Error] Missing deployments.json. Run 'npm run deploy' first.`);
  process.exit(1);
}

const deployment = JSON.parse(fs.readFileSync(deployPath, "utf8"));
const rpcUrl = process.env.RPC_URL || deployment.network.rpcUrl || "http://127.0.0.1:8545";
const provider = new ethers.JsonRpcProvider(rpcUrl);

// Deterministic Anvil keys
const GOV_KEY       = "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80"; // Account 0
const ATTESTER_KEY  = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"; // Account 1
const FEEDER_KEY    = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"; // Account 2

const govWallet      = new ethers.Wallet(GOV_KEY, provider);
const attesterWallet = new ethers.Wallet(ATTESTER_KEY, provider);
const feederWallet   = new ethers.Wallet(FEEDER_KEY, provider);

const asoContract = new ethers.Contract(
  deployment.contracts.ASOAdapter.address,
  deployment.contracts.ASOAdapter.abi,
  attesterWallet
);

const osmContract = new ethers.Contract(
  deployment.contracts.VanillaOSM.address,
  deployment.contracts.VanillaOSM.abi,
  feederWallet
);

const sentinelContract = new ethers.Contract(
  deployment.contracts.SentinelRegistry.address,
  deployment.contracts.SentinelRegistry.abi,
  govWallet
);

const riskEngineContract = deployment.contracts.RiskEngine ? new ethers.Contract(
  deployment.contracts.RiskEngine.address,
  deployment.contracts.RiskEngine.abi,
  govWallet
) : null;

const lendingAsoContract = new ethers.Contract(
  deployment.contracts.ToyLendingMarketASO.address,
  deployment.contracts.ToyLendingMarketASO.abi,
  govWallet
);

const MOCK_SOURCE_URL = process.env.MOCK_SOURCE_URL || "http://localhost:4000";
const POLL_INTERVAL_MS = Number(process.env.POLL_INTERVAL_MS) || 10000; // 10 seconds
const STATUS_PORT = Number(process.env.STATUS_PORT) || 4001;

const SOURCE_ADDRESSES = {
  ondo: "0x1111111111111111111111111111111111111111",
  coinbase: "0x2222222222222222222222222222222222222222",
  kraken: "0x3333333333333333333333333333333333333333",
  fed: "0x4444444444444444444444444444444444444444"
};

const RISK_STATE_NAMES = ["FRESH", "WATCH", "STALE", "DISPUTED", "PROTECTIVE", "RECOVERING"];

// Telemetry & Historical Cache
let cycleCount = 0;
let lastPollTimestamp = Date.now();
let lastTxHash = null;
let lastBlockNumber = null;
let lastSubmittedPrice = 100.0;
let lastDivergenceBps = 0;
let serviceStartTime = Date.now();

let cachedWeightedMedian = 100.0;
let cachedSimpleConsensus = 100.0;
let cachedTwapPrice = 100.0;
let cachedEffectivePrice = 100.0;
let cachedVelocityBps = 0;
let priceHistory = [100.0, 100.0, 100.0, 100.0, 100.0];

let cachedSourceCostRanking = [];
let cachedCheapestSource = null;
let cachedCostGateDecision = {
  passed: true,
  proposedPrice: 100.0,
  effectivePrice: 100.0,
  costEstimate: 120000,
  extractableValue: 0,
  reason: "Normal operating conditions: spot within baseline band"
};

let cachedSentinelState = "FRESH";
let cachedSentinelCeiling = 500000;
let cachedRecoveryStreak = 0;
let cachedCurrentTrigger = "Genesis: SentinelRegistry deployed";

let cachedGamma = 500000;
let cachedEpochGrowthCap = 100000;
let cachedSlowAnchor = 100.0;
let cachedAttackEconomics = {
  attackerNetCost: 15000,
  maxExtraBorrow: 12000,
  netResult: -3000,
  margin: 12500,
  coalitionMask: 3
};

let cachedVaultIntegrity = {
  impliedRate: 1.0,
  expectedRate: 1.0,
  healthy: true,
  lastJumpPct: 0
};

// Historical Cycle Snapshots for Price Chart (GET /cycle/history)
let cycleHistory = [
  { cycle: 1, timestamp: Math.floor(Date.now() / 1000) - 40, simpleMean: 100.0, weightedMedian: 100.0, twap: 100.0, effectivePrice: 100.0, sentinelState: "FRESH", trigger: "Healthy cycle", gateDecision: { passed: true, reason: "Normal conditions" }, proposedPrice: 100.0, attackCost: 50000, extractableValue: 0, debtCeiling: 500000, recoveryStreak: 0, isFresh: true },
  { cycle: 2, timestamp: Math.floor(Date.now() / 1000) - 30, simpleMean: 100.01, weightedMedian: 100.01, twap: 100.0, effectivePrice: 100.01, sentinelState: "FRESH", trigger: "Healthy cycle", gateDecision: { passed: true, reason: "Normal conditions" }, proposedPrice: 100.01, attackCost: 50000, extractableValue: 0, debtCeiling: 500000, recoveryStreak: 0, isFresh: true },
  { cycle: 3, timestamp: Math.floor(Date.now() / 1000) - 20, simpleMean: 100.02, weightedMedian: 100.02, twap: 100.01, effectivePrice: 100.02, sentinelState: "FRESH", trigger: "Healthy cycle", gateDecision: { passed: true, reason: "Normal conditions" }, proposedPrice: 100.02, attackCost: 50000, extractableValue: 0, debtCeiling: 500000, recoveryStreak: 0, isFresh: true },
  { cycle: 4, timestamp: Math.floor(Date.now() / 1000) - 10, simpleMean: 100.01, weightedMedian: 100.02, twap: 100.01, effectivePrice: 100.02, sentinelState: "FRESH", trigger: "Healthy cycle", gateDecision: { passed: true, reason: "Normal conditions" }, proposedPrice: 100.02, attackCost: 50000, extractableValue: 0, debtCeiling: 500000, recoveryStreak: 0, isFresh: true }
];

function recordCycleSnapshot() {
  const snapshot = {
    cycle: cycleCount,
    timestamp: Math.floor(Date.now() / 1000),
    simpleMean: cachedSimpleConsensus,
    weightedMedian: cachedWeightedMedian,
    twap: cachedTwapPrice,
    effectivePrice: cachedEffectivePrice,
    sentinelState: cachedSentinelState,
    trigger: cachedCurrentTrigger,
    gateDecision: cachedCostGateDecision,
    proposedPrice: cachedCostGateDecision ? cachedCostGateDecision.proposedPrice : cachedWeightedMedian,
    attackCost: cachedCostGateDecision ? cachedCostGateDecision.costEstimate : 0,
    extractableValue: cachedCostGateDecision ? cachedCostGateDecision.extractableValue : 0,
    debtCeiling: cachedSentinelCeiling,
    recoveryStreak: cachedRecoveryStreak,
    gamma: cachedGamma,
    epochGrowthCap: cachedEpochGrowthCap,
    isFresh: cachedSentinelState === "FRESH"
  };
  cycleHistory.push(snapshot);
  if (cycleHistory.length > 100) cycleHistory.shift();
}

// Express Status Server
const statusApp = express();
statusApp.use(cors());
statusApp.use(express.json());

statusApp.get("/cycle/history", (req, res) => {
  res.json({
    history: cycleHistory,
    totalCycles: cycleCount,
    latest: cycleHistory[cycleHistory.length - 1] || null
  });
});
statusApp.get("/history", (req, res) => {
  res.json({
    history: cycleHistory,
    totalCycles: cycleCount,
    latest: cycleHistory[cycleHistory.length - 1] || null
  });
});

statusApp.get("/validation-results", (req, res) => {
  const validationPath = path.join(rootDir, "data", "derived", "validation_results.json");
  if (fs.existsSync(validationPath)) {
    res.sendFile(validationPath);
  } else {
    res.status(404).json({ error: "Validation results not found" });
  }
});

statusApp.get("/status", async (req, res) => {
  const now = Date.now();
  const elapsedSec = Math.floor((now - lastPollTimestamp) / 1000);
  const nextInSec = Math.max(0, Math.ceil((POLL_INTERVAL_MS - (now - lastPollTimestamp)) / 1000));
  const uptimeSec = Math.floor((now - serviceStartTime) / 1000);
  const uptimeFormatted = `${Math.floor(uptimeSec / 60)}m ${uptimeSec % 60}s`;

  let currentEpochBorrowed = 0;
  try {
    const borrowerAddr = "0x90F79bf6EB2c4f870365E785982E1f101E93b906";
    const b = await lendingAsoContract.getBorrowedThisEpoch(borrowerAddr);
    currentEpochBorrowed = Number(ethers.formatEther(b));
  } catch (_) {}

  // Fetch live values from RiskEngine if available
  if (riskEngineContract) {
    try {
      const g = await riskEngineContract.gamma();
      cachedGamma = Number(ethers.formatEther(g));
      const egc = await riskEngineContract.epochGrowthCap();
      cachedEpochGrowthCap = Number(ethers.formatEther(egc));
      const sa = await riskEngineContract.slowAnchorPrice();
      cachedSlowAnchor = Number(ethers.formatEther(sa));
      
      const eco = await riskEngineContract.attackEconomics(1500); // 15% move
      cachedAttackEconomics = {
        attackerNetCost: Number(ethers.formatEther(eco[0])),
        maxExtraBorrow: Number(ethers.formatEther(eco[1])),
        netResult: Number(ethers.formatEther(eco[2])),
        margin: Number(eco[3]),
        coalitionMask: Number(eco[4])
      };
    } catch (reErr) {
      // RiskEngine call fallback
    }
  }

  res.json({
    cycleCount,
    lastPollAgoSec: elapsedSec,
    nextPollInSec: nextInSec,
    uptimeFormatted,
    lastTxHash,
    lastBlockNumber,
    lastDivergenceBps,
    lastSubmittedPrice,
    weightedMedianPrice: cachedWeightedMedian,
    simpleConsensusPrice: cachedSimpleConsensus,
    twapPrice: cachedTwapPrice,
    effectivePrice: cachedEffectivePrice,
    priceVelocityBps: cachedVelocityBps,
    sourceCostRanking: cachedSourceCostRanking,
    cheapestSource: cachedCheapestSource,
    costGateDecision: cachedCostGateDecision,
    sentinelState: cachedSentinelState,
    sentinelCeiling: cachedSentinelCeiling,
    recoveryStreak: cachedRecoveryStreak,
    sentinelTrigger: cachedCurrentTrigger,
    gamma: cachedGamma,
    epochGrowthCap: cachedEpochGrowthCap,
    slowAnchor: cachedSlowAnchor,
    attackEconomics: cachedAttackEconomics,
    epochBorrowCap: {
      maxPerEpoch: cachedEpochGrowthCap || 50000,
      currentEpochBorrowed,
      epochRemaining: Math.max(0, (cachedEpochGrowthCap || 50000) - currentEpochBorrowed)
    },
    vaultIntegrity: cachedVaultIntegrity,
    history: cycleHistory.slice(-20)
  });
});

statusApp.listen(STATUS_PORT, () => {
  console.log(`[Status Server] Health & risk telemetry endpoint running on http://localhost:${STATUS_PORT}/status`);
});

// Liquidity-Weighted Median Algorithm (Pure Javascript matching RiskEngine.sol)
function calculateWeightedMedian(sources) {
  if (!sources || sources.length === 0) return 100.0;
  const sorted = [...sources].sort((a, b) => a.price - b.price);
  const totalWeight = sorted.reduce((sum, s) => sum + (s.liquidityWeight || 25), 0);
  const halfWeight = totalWeight / 2;

  let cumulative = 0;
  for (const s of sorted) {
    cumulative += (s.liquidityWeight || 25);
    if (cumulative > halfWeight) {
      return Number(s.price.toFixed(4));
    }
  }
  return Number(sorted[sorted.length - 1].price.toFixed(4));
}

// Manipulation Cost Estimate per Source
function estimateSourceManipulationCost(source, priceMoveBps) {
  const weight = source.liquidityWeight || 10;
  const move = Math.max(priceMoveBps, 1);
  const difficultyFactor = (move * move) / 10000;
  // Base market depth = $500,000 USD
  const cost = (500000 * (weight / 100) * difficultyFactor);
  return Math.round(cost);
}

async function pollAndAttest() {
  cycleCount++;
  lastPollTimestamp = Date.now();
  const cycleTime = new Date().toLocaleTimeString();
  console.log(`\n--- [Cycle #${cycleCount} @ ${cycleTime}] Polling mock sources & assessing manipulation cost ---`);

  let sourcesData;
  try {
    const res = await fetch(`${MOCK_SOURCE_URL}/sources`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    sourcesData = await res.json();
  } catch (err) {
    console.error(`[Error] Failed to connect to mock sources at ${MOCK_SOURCE_URL}: ${err.message}`);
    return;
  }

  const { sources, feederActive, vault } = sourcesData;
  if (vault) {
    cachedVaultIntegrity = {
      impliedRate: vault.impliedRate,
      expectedRate: 1.0,
      healthy: vault.healthy,
      lastJumpPct: vault.lastDonationJumpPct || 0
    };
  }

  const onlineSources = sources.filter((s) => s.status === "ONLINE");
  console.log(`[Quorum] Online sources: ${onlineSources.length}/${sources.length}`);

  // Check for offline sources (Killing one source produces STALE)
  const offlineSources = sources.filter((s) => s.status === "OFFLINE");
  if (offlineSources.length > 0) {
    const offlineNames = offlineSources.map((s) => s.name.split(" ")[0]).join(", ");
    const triggerDesc = `Stale source: ${offlineNames} offline (freshness check elapsed)`;
    console.warn(`[SENTINEL ALERT] ⚠️ Source server offline: ${triggerDesc}`);
    try {
      const sentGov = sentinelContract.connect(govWallet);
      await (await sentGov.updateRiskSignal(2, triggerDesc)).wait(); // 2 = STALE
    } catch (e) {
      console.warn("[Sentinel Stale Signal]", e.message);
    }
    await handleSentinelCheck(false, triggerDesc);
    recordCycleSnapshot();
    await handleFeederCycle(feederActive, onlineSources);
    return;
  }

  // 1. Quorum Check (N >= 3)
  if (onlineSources.length < 3) {
    console.warn(`[ASO-REJECTED] ❌ Quorum failure: Got ${onlineSources.length} online sources, minimum is 3.`);
    await handleSentinelCheck(false, "Quorum failure (N < 3 sources online)");
    recordCycleSnapshot();
    await handleFeederCycle(feederActive, onlineSources);
    return;
  }

  // 2. Simple Mean/Median Consensus
  const sortedPrices = onlineSources.map((s) => s.price).sort((a, b) => a - b);
  const minPrice = sortedPrices[0];
  const maxPrice = sortedPrices[sortedPrices.length - 1];
  const mid = Math.floor(sortedPrices.length / 2);
  const simpleMedian = sortedPrices.length % 2 !== 0 ? sortedPrices[mid] : (sortedPrices[mid - 1] + sortedPrices[mid]) / 2;
  cachedSimpleConsensus = Number(simpleMedian.toFixed(4));

  // 3. Liquidity-Weighted Median (v2)
  cachedWeightedMedian = calculateWeightedMedian(onlineSources);

  // 4. TWAP & Price Velocity
  priceHistory.push(cachedWeightedMedian);
  if (priceHistory.length > 5) priceHistory.shift();
  cachedTwapPrice = Number((priceHistory.reduce((a, b) => a + b, 0) / priceHistory.length).toFixed(4));
  const prevPrice = priceHistory[priceHistory.length - 2] || cachedWeightedMedian;
  cachedVelocityBps = Math.round((Math.abs(cachedWeightedMedian - prevPrice) / prevPrice) * 10000);

  const spread = maxPrice - minPrice;
  const divergenceBps = Math.round((spread / cachedWeightedMedian) * 10000);
  lastDivergenceBps = divergenceBps;

  console.log(`[Consensus v2] Simple Mean/Median: $${cachedSimpleConsensus.toFixed(2)} | Weighted Median: $${cachedWeightedMedian.toFixed(2)} | TWAP: $${cachedTwapPrice.toFixed(2)} | Spread: ${divergenceBps} bps`);

  // 5. Weakest Link Panel: Rank sources by manipulation cost
  const ranking = onlineSources.map((s) => {
    const moveFromTwapBps = Math.round((Math.abs(s.price - cachedTwapPrice) / cachedTwapPrice) * 10000);
    const cost = estimateSourceManipulationCost(s, Math.max(moveFromTwapBps, 100)); // min 100 bps for baseline
    return {
      id: s.id,
      name: s.name,
      price: s.price,
      weight: s.liquidityWeight,
      moveBps: moveFromTwapBps,
      costUsd: cost,
      isCheapest: false
    };
  }).sort((a, b) => a.costUsd - b.costUsd);

  if (ranking.length > 0) ranking[0].isCheapest = true;
  cachedSourceCostRanking = ranking;
  cachedCheapestSource = ranking[0] || null;

  console.log(`[Weakest Link] Cheapest source to fake: ${cachedCheapestSource?.name} (Cost: $${cachedCheapestSource?.costUsd.toLocaleString()})`);

  // 6. Check Vault Integrity Sanity Check (Venus wUSDM/vTHE Bare Donation Vector)
  if (vault && !vault.healthy) {
    console.warn(`[SENTINEL ALERT] ⚠️ Vault integrity check failed! Implied rate jumped ${vault.lastDonationJumpPct.toFixed(2)}% without share minting.`);
    try {
      const sentGov = sentinelContract.connect(govWallet);
      await (await sentGov.updateRiskSignal(3, `Vault donation attack detected: share rate jumped ${vault.lastDonationJumpPct.toFixed(1)}%`)).wait();
    } catch (_) {}
    await handleSentinelCheck(true, `DISPUTED: Vault share inflation attack (${vault.lastDonationJumpPct.toFixed(1)}% jump)`);
    recordCycleSnapshot();
    return;
  }

  // 7. Manipulation Cost vs Extractable Value Gate
  // extractable = (1000 units collateral * (proposedPrice - TWAP) * 80% LTV)
  let costGatePassed = true;
  let effectivePrice = cachedWeightedMedian;
  let reason = "Normal operating conditions: spot aligned with TWAP";

  if (cachedWeightedMedian > cachedTwapPrice) {
    const delta = cachedWeightedMedian - cachedTwapPrice;
    const extractable = 1000 * delta * 0.80; // $800 unlocked per $1 move
    const cheapestCost = cachedCheapestSource ? cachedCheapestSource.costUsd : 50000;
    const safetyMargin = 1.2;
    const requiredCost = extractable * safetyMargin;

    if (cheapestCost < requiredCost) {
      costGatePassed = false;
      effectivePrice = cachedTwapPrice; // clamp to TWAP!
      reason = `COST-GATE BLOCKED: Cheap manipulation! Cost ($${cheapestCost.toLocaleString()}) < 1.2x Extractable ($${Math.round(requiredCost).toLocaleString()})`;
      console.warn(`[COST-GATE] ❌ ${reason}`);
      console.warn(`[COST-GATE] Clamping effective price to TWAP: $${effectivePrice.toFixed(2)}`);

      // Trigger PROTECTIVE state in SentinelRegistry!
      try {
        const sentGov = sentinelContract.connect(govWallet);
        await (await sentGov.updateRiskSignal(4, reason)).wait(); // 4 = PROTECTIVE
      } catch (e) {
        console.warn("[Sentinel Signal Error]", e.message);
      }
    } else {
      costGatePassed = true;
      effectivePrice = cachedWeightedMedian;
      reason = `COST-GATE PASSED: Price move backed by $${cheapestCost.toLocaleString()} attack difficulty`;
      console.log(`[COST-GATE] ✅ ${reason}`);
    }

    cachedCostGateDecision = {
      passed: costGatePassed,
      proposedPrice: cachedWeightedMedian,
      effectivePrice: effectivePrice,
      costEstimate: cheapestCost,
      extractableValue: Math.round(extractable),
      reason
    };
  } else {
    cachedCostGateDecision = {
      passed: true,
      proposedPrice: cachedWeightedMedian,
      effectivePrice: cachedWeightedMedian,
      costEstimate: cachedCheapestSource?.costUsd || 0,
      extractableValue: 0,
      reason: "Price <= TWAP: zero extractable value unlocked"
    };
  }
  cachedEffectivePrice = effectivePrice;

  // 8. Divergence Bounds Check
  if (divergenceBps > 50) {
    console.warn(`[ASO-REJECTED] ❌ Divergence bound breached: ${divergenceBps} bps > 50 bps tolerance.`);
    await handleSentinelCheck(false, `Divergence breached: ${divergenceBps} bps > 50 bps`);
    recordCycleSnapshot();
    await handleFeederCycle(feederActive, onlineSources);
    return;
  }

  // 9. Submit On-Chain Attestation to ASOAdapter
  try {
    const network = await provider.getNetwork();
    const chainId = network.chainId;
    const now = Math.floor(Date.now() / 1000);
    const windowStart = BigInt(now - 6);
    const windowEnd = BigInt(now - 1);

    const priceWei = ethers.parseEther(effectivePrice.toFixed(6));
    const minPriceWei = ethers.parseEther(minPrice.toFixed(6));
    const maxPriceWei = ethers.parseEther(maxPrice.toFixed(6));

    const sourceAddrs = onlineSources.map((s) => SOURCE_ADDRESSES[s.id] || ethers.ZeroAddress);
    const sourcesHash = ethers.solidityPackedKeccak256(["address[]"], [sourceAddrs]);

    const abiCoder = ethers.AbiCoder.defaultAbiCoder();
    const encodedStruct = abiCoder.encode(
      ["uint256", "uint256", "uint256", "bytes32", "uint256", "uint256", "uint256", "address"],
      [priceWei, minPriceWei, maxPriceWei, sourcesHash, windowStart, windowEnd, chainId, deployment.contracts.ASOAdapter.address]
    );
    const structHash = ethers.keccak256(encodedStruct);
    const signature = await attesterWallet.signMessage(ethers.getBytes(structHash));

    const attestationStruct = {
      price: priceWei,
      minPrice: minPriceWei,
      maxPrice: maxPriceWei,
      sources: sourceAddrs,
      windowStart,
      windowEnd,
      signature
    };

    console.log(`[ASO-SIGN] Signed EIP-191 digest: ${structHash.slice(0, 18)}... by ${attesterWallet.address}`);
    const tx = await asoContract.submit(attestationStruct);
    const receipt = await tx.wait();

    lastTxHash = receipt.hash;
    lastBlockNumber = receipt.blockNumber;
    lastSubmittedPrice = effectivePrice;

    console.log(`[ASO-SUBMIT-TX] ✅ Attestation accepted on-chain! Tx: ${receipt.hash.slice(0, 16)}... | Block #${receipt.blockNumber} | Price: $${effectivePrice.toFixed(2)}`);
  } catch (err) {
    console.error(`[ASO-SUBMIT-ERROR] ${err.message}`);
  }

  // 10. Update Sentinel State
  await handleSentinelCheck(true, costGatePassed ? "Healthy cycle" : reason);

  // Record cycle snapshot for live charts
  recordCycleSnapshot();

  // 11. Vanilla OSM Feeder
  await handleFeederCycle(feederActive, onlineSources);
}

async function handleSentinelCheck(oracleValid, triggerDesc) {
  try {
    const currentStateNum = Number(await sentinelContract.currentState());
    if (currentStateNum === 3 && oracleValid && (!cachedCostGateDecision || cachedCostGateDecision.passed)) {
      console.log(`[SENTINEL AUTO-RESOLVE] Resolving dispute as sources & vault are healthy...`);
      try {
        const sentGov = sentinelContract.connect(govWallet);
        const resTx = await sentGov.resolve("Automated recovery: vault and market feeds healthy");
        await resTx.wait();
      } catch (resErr) {
        console.warn(`[SENTINEL-RESOLVE-WARN] ${resErr.message}`);
      }
    }

    const tx = await sentinelContract.checkAndUpdate();
    await tx.wait();

    const stateNum = Number(await sentinelContract.currentState());
    cachedSentinelState = RISK_STATE_NAMES[stateNum] || "FRESH";
    const ceilingWei = await sentinelContract.debtCeiling();
    cachedSentinelCeiling = Number(ethers.formatEther(ceilingWei));
    cachedRecoveryStreak = Number(await sentinelContract.recoveryStreak());
    cachedCurrentTrigger = triggerDesc;

    console.log(`[SENTINEL v2] State: ${cachedSentinelState} | Ceiling: $${Math.round(cachedSentinelCeiling).toLocaleString()} | Recovery streak: ${cachedRecoveryStreak}/3 | Trigger: "${triggerDesc}"`);
  } catch (err) {
    console.warn(`[SENTINEL-ERROR] ${err.message}`);
  }
}

async function handleFeederCycle(feederActive, onlineSources) {
  if (!feederActive) {
    console.log(`[OSM-FEEDER] ⚠️ Feeder status is OFFLINE (Omission simulated). No poke() sent.`);
    return;
  }
  try {
    const rawPrice = onlineSources.length > 0 ? onlineSources[0].price : 100.0;
    const priceWei = ethers.parseEther(rawPrice.toFixed(4));
    console.log(`[OSM-FEEDER] Feeder ONLINE: Sending poke($${rawPrice.toFixed(2)})...`);
    const tx = await osmContract.poke(priceWei);
    const rc = await tx.wait();
    console.log(`[OSM-FEEDER] ✅ Poke accepted: Block #${rc.blockNumber}`);

    await fetch(`${MOCK_SOURCE_URL}/feeder/record-poke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ timestamp: Math.floor(Date.now() / 1000), price: rawPrice })
    }).catch(() => {});
  } catch (err) {
    console.warn(`[OSM-FEEDER-ERROR] ${err.message}`);
  }
}

// Start polling loop
console.log(`========================================================================`);
console.log(`   ORIGIN // ASO v2 — LIVE RISK ENGINE & ATTESTATION PIPELINE           `);
console.log(`========================================================================`);
console.log(`[Config] EVM RPC:           ${rpcUrl}`);
console.log(`[Config] ASO Contract:      ${deployment.contracts.ASOAdapter.address}`);
console.log(`[Config] Sentinel:          ${deployment.contracts.SentinelRegistry.address}`);
console.log(`[Config] RiskEngine:        ${deployment.contracts.RiskEngine?.address}`);
console.log(`[Config] Polling Cadence:   Every ${POLL_INTERVAL_MS / 1000}s`);
console.log(`[Config] Status Endpoint:   http://localhost:${STATUS_PORT}/status`);
console.log(`========================================================================\n`);

pollAndAttest();
setInterval(pollAndAttest, POLL_INTERVAL_MS);
