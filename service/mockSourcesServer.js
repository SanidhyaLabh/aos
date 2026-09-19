// SPDX-License-Identifier: MIT
/**
 * @file mockSourcesServer.js (Origin // ASO v2)
 * @notice Express server exposing 4 independent mock price feed sources with
 * liquidity weights, manipulation simulation controls, RWA vault donation check simulation,
 * and grounded Gemini AI oracle risk analysis.
 */

import express from "express";
import cors from "cors";

const app = express();
const PORT = process.env.PORT || 4000;

app.use(cors());
app.use(express.json());

// In-memory state for 4 mock sources with liquidity weights (sum = 100%)
const sourceConfigs = {
  ondo: {
    id: "ondo",
    name: "Ondo / Securitize RWA Custodian Feed",
    type: "RWA Custodian NAV",
    nominalOffset: 0.02,
    latencyMs: 38,
    status: "ONLINE",
    overridePrice: null,
    liquidityWeight: 35 // 35% of total market depth
  },
  coinbase: {
    id: "coinbase",
    name: "Coinbase Prime Institutional Index",
    type: "Institutional Spot",
    nominalOffset: 0.03,
    latencyMs: 24,
    status: "ONLINE",
    overridePrice: null,
    liquidityWeight: 40 // 40% of total market depth
  },
  kraken: {
    id: "kraken",
    name: "Kraken Treasury Benchmark",
    type: "Exchange Orderbook",
    nominalOffset: -0.02,
    latencyMs: 31,
    status: "ONLINE",
    overridePrice: null,
    liquidityWeight: 15 // 15% of total market depth (Thin)
  },
  fed: {
    id: "fed",
    name: "Fed H.15 / Multipli Yield Interbank",
    type: "Interbank Reference Rate",
    nominalOffset: 0.01,
    latencyMs: 45,
    status: "ONLINE",
    overridePrice: null,
    liquidityWeight: 10 // 10% of total market depth (Thinnest link)
  }
};

let globalState = {
  baseMarketPrice: 100.0,
  shockPercentage: 0,
  feederActive: false, // Default false to reproduce outage or toggleable
  lastPokeTimestamp: null,
  lastPokePrice: null
};

// Vault sanity check state (Venus wUSDM/vTHE style bare donation vector)
let vaultState = {
  address: "0xBAdf00d111111111111111111111111111111111",
  name: "Origin RWA Senior Yield Vault (ERC-4626)",
  totalAssets: 1000000.0, // $1,000,000 USD assets
  totalSupply: 1000000.0, // 1,000,000 shares
  baseRate: 1.0,          // 1.0000 assets per share
  lastDonationJumpPct: 0,
  underAttack: false
};

// Helper to compute live price for a source
function getSourcePrice(id) {
  const src = sourceConfigs[id];
  if (!src) return null;

  if (src.overridePrice !== null) {
    return Number(src.overridePrice.toFixed(4));
  }

  // Base price adjusted by macro shock + source-specific basis offset
  const shockedBase = globalState.baseMarketPrice * (1 - globalState.shockPercentage / 100);
  const finalPrice = shockedBase + src.nominalOffset;
  return Number(finalPrice.toFixed(4));
}

function formatSource(id) {
  const src = sourceConfigs[id];
  const now = Math.floor(Date.now() / 1000);
  return {
    id: src.id,
    name: src.name,
    type: src.type,
    price: getSourcePrice(id),
    status: src.status,
    latencyMs: src.latencyMs,
    liquidityWeight: src.liquidityWeight,
    lastUpdated: now,
    lastPokeTimestamp: globalState.lastPokeTimestamp,
    lastPokePrice: globalState.lastPokePrice
  };
}

// --- Source Endpoints ---
app.get("/sources", (req, res) => {
  const sources = Object.keys(sourceConfigs).map(formatSource);
  
  // Auto-decrement hold cycles if active
  Object.keys(sourceConfigs).forEach((id) => {
    const src = sourceConfigs[id];
    if (typeof src.holdCycles === "number" && src.holdCycles > 0) {
      src.holdCycles--;
      if (src.holdCycles === 0) {
        src.overridePrice = null;
        src.holdCycles = null;
        console.log(`[MockSources] Hold cycles completed for source ${id}. Reverting to normal pricing.`);
      }
    }
  });

  res.json({
    sources,
    baseMarketPrice: globalState.baseMarketPrice,
    feederActive: globalState.feederActive,
    shockPercentage: globalState.shockPercentage,
    vault: {
      ...vaultState,
      impliedRate: vaultState.totalAssets / vaultState.totalSupply,
      healthy: !vaultState.underAttack
    }
  });
});

Object.keys(sourceConfigs).forEach((id) => {
  app.get(`/${id}/price`, (req, res) => {
    res.json(formatSource(id));
  });
  app.get(`/sources/${id}/price`, (req, res) => {
    res.json(formatSource(id));
  });

  const shockHandler = (req, res) => {
    const src = sourceConfigs[id];
    const { price, skewPercent, latencyMs, status, liquidityWeight, holdCycles } = req.body;

    if (price !== undefined) {
      src.overridePrice = Number(price);
    } else if (skewPercent !== undefined) {
      const base = globalState.baseMarketPrice * (1 - globalState.shockPercentage / 100);
      src.overridePrice = Number((base * (1 + skewPercent / 100)).toFixed(4));
    }

    if (latencyMs !== undefined) {
      src.latencyMs = Number(latencyMs);
    }

    if (status !== undefined) {
      src.status = status;
    }

    if (liquidityWeight !== undefined) {
      src.liquidityWeight = Number(liquidityWeight);
    }

    if (holdCycles !== undefined) {
      src.holdCycles = Number(holdCycles);
    }

    console.log(`[MockSources] Updated source ${id}: price=${getSourcePrice(id)}, weight=${src.liquidityWeight}%, status=${src.status}, holdCycles=${src.holdCycles || 'indefinite'}`);
    res.json(formatSource(id));
  };
  app.post(`/${id}/simulate-shock`, shockHandler);
  app.post(`/sources/${id}/simulate-shock`, shockHandler);

  // POST /sources/:id/weight
  app.post(`/sources/${id}/weight`, (req, res) => {
    const src = sourceConfigs[id];
    if (req.body.weight !== undefined) {
      src.liquidityWeight = Number(req.body.weight);
    }
    res.json(formatSource(id));
  });

  // POST /sources/:id/toggle
  app.post(`/sources/${id}/toggle`, (req, res) => {
    const src = sourceConfigs[id];
    src.status = src.status === "ONLINE" ? "OFFLINE" : "ONLINE";
    console.log(`[MockSources] Toggled ${id} status: ${src.status}`);
    res.json(formatSource(id));
  });
});

// --- Macro Collateral Shock Slider Endpoint ---
app.post("/sources/simulate-shock-all", (req, res) => {
  const { shockPercentage, basePrice } = req.body;
  if (shockPercentage !== undefined) {
    globalState.shockPercentage = Number(shockPercentage);
  }
  if (basePrice !== undefined) {
    globalState.baseMarketPrice = Number(basePrice);
  }
  // Clear any single-source overrides when applying macro shock
  Object.keys(sourceConfigs).forEach((id) => {
    sourceConfigs[id].overridePrice = null;
  });

  console.log(`[MockSources] Applied macro collateral shock: shockPercentage=${globalState.shockPercentage}%, effectiveBase=$${(globalState.baseMarketPrice * (1 - globalState.shockPercentage / 100)).toFixed(2)}`);
  res.json({
    baseMarketPrice: globalState.baseMarketPrice,
    shockPercentage: globalState.shockPercentage,
    sources: Object.keys(sourceConfigs).map(formatSource)
  });
});

// --- Reset to Baseline ---
app.post("/sources/reset", (req, res) => {
  globalState.shockPercentage = 0;
  globalState.baseMarketPrice = 100.0;
  sourceConfigs.ondo.liquidityWeight = 35;
  sourceConfigs.coinbase.liquidityWeight = 40;
  sourceConfigs.kraken.liquidityWeight = 15;
  sourceConfigs.fed.liquidityWeight = 10;
  Object.keys(sourceConfigs).forEach((id) => {
    sourceConfigs[id].overridePrice = null;
    sourceConfigs[id].status = "ONLINE";
  });
  vaultState.totalAssets = 1000000.0;
  vaultState.totalSupply = 1000000.0;
  vaultState.lastDonationJumpPct = 0;
  vaultState.underAttack = false;
  console.log("[MockSources] Reset all sources and vault to baseline $100.00");
  res.json({
    status: "reset",
    sources: Object.keys(sourceConfigs).map(formatSource),
    vault: vaultState
  });
});

// --- Feeder Process Controls ---
app.get("/feeder/status", (req, res) => {
  res.json({
    active: globalState.feederActive,
    lastPokeTimestamp: globalState.lastPokeTimestamp,
    lastPokePrice: globalState.lastPokePrice
  });
});

app.post("/feeder/toggle", (req, res) => {
  if (req.body.active !== undefined) {
    globalState.feederActive = Boolean(req.body.active);
  } else {
    globalState.feederActive = !globalState.feederActive;
  }
  console.log(`[MockSources] Feeder active toggled to: ${globalState.feederActive}`);
  res.json({ active: globalState.feederActive });
});

app.post("/feeder/record-poke", (req, res) => {
  const { timestamp, price } = req.body;
  globalState.lastPokeTimestamp = timestamp || Math.floor(Date.now() / 1000);
  globalState.lastPokePrice = price;
  res.json({ success: true });
});

// --- RWA Vault Sanity Check Endpoints (Venus wUSDM/vTHE Vector) ---
app.get("/vault/status", (req, res) => {
  const impliedRate = vaultState.totalAssets / vaultState.totalSupply;
  res.json({
    ...vaultState,
    impliedRate,
    healthy: !vaultState.underAttack
  });
});

app.post("/vault/simulate-donation", (req, res) => {
  const donationAmount = Number(req.body.amount || 350000);
  vaultState.totalAssets += donationAmount;
  vaultState.underAttack = true;
  vaultState.lastDonationJumpPct = ((vaultState.totalAssets / vaultState.totalSupply - 1.0) * 100);
  console.log(`[MockSources] Vault donation attack simulated: +$${donationAmount}, impliedRate=${(vaultState.totalAssets / vaultState.totalSupply).toFixed(4)}`);
  res.json({
    success: true,
    message: "Bare asset transfer executed without minting shares",
    vault: {
      ...vaultState,
      impliedRate: vaultState.totalAssets / vaultState.totalSupply,
      healthy: false
    }
  });
});

app.post("/vault/reset", (req, res) => {
  vaultState.totalAssets = 1000000.0;
  vaultState.totalSupply = 1000000.0;
  vaultState.lastDonationJumpPct = 0;
  vaultState.underAttack = false;
  res.json({ success: true, vault: vaultState });
});

// --- Ask Anything / Gemini AI Telemetry Endpoint (Grounded) ---
const GEMINI_API_KEY = process.env.GEMINI_API_KEY || "";

app.post("/api/ask", async (req, res) => {
  const { query, liveContext } = req.body;
  if (!query) {
    return res.status(400).json({ error: "Query is required" });
  }

  let attestationStatus = {};
  try {
    const statusRes = await fetch("http://localhost:4001/status");
    if (statusRes.ok) attestationStatus = await statusRes.json();
  } catch (_) {}

  const groundedOn = {
    timestamp: new Date().toISOString(),
    asoPrice: liveContext?.asoPriceUsd ?? "unknown",
    weightedMedianPrice: attestationStatus?.weightedMedianPrice ?? "unknown",
    simpleConsensusPrice: attestationStatus?.simpleConsensusPrice ?? "unknown",
    twapPrice: attestationStatus?.twapPrice ?? "unknown",
    effectivePrice: attestationStatus?.effectivePrice ?? "unknown",
    cheapestSource: attestationStatus?.cheapestSource ?? "unknown",
    costGateDecision: attestationStatus?.costGateDecision ?? "unknown",
    sentinelState: liveContext?.sentinelState ?? attestationStatus?.sentinelState ?? "FRESH",
    sentinelCeiling: liveContext?.sentinelCeiling ?? attestationStatus?.sentinelCeiling ?? 500000,
    recoveryStreak: liveContext?.recoveryStreak ?? attestationStatus?.recoveryStreak ?? 0,
    badDebtAccruedUsd: liveContext?.badDebtAccruedUsd ?? 0,
    epochBorrowCap: attestationStatus?.epochBorrowCap ?? { maxPerEpoch: 50000 },
    vaultIntegrity: attestationStatus?.vaultIntegrity ?? { healthy: !vaultState.underAttack },
    contracts: liveContext?.contracts ?? {}
  };

  const systemInstruction = `You are the Origin // ASO v2 (Attested Staleness Oracle & Manipulation-Cost-Aware Lending Protection) Cryptographic & Protocol Risk Specialist for the Multipli Hackathon 2026.
Your job is to provide concise, technically accurate, authoritative answers to questions about DeFi oracles, market manipulation costs, liquidity-weighted medians, and bounded-loss epoch caps.

CRITICAL: Answer from the provided data and verified security research (Mango Markets $117M 2022, Venus $3.7M March 2026, Silo Finance $392K April 2026, Angeris & Chitra 2020).

Origin ASO v2 Architecture:
1. Liquidity-Weighted Median: Sources are weighted by market depth; cumulative weight must cross 50% to move consensus. Stops thin-source pump attacks.
2. Manipulation Cost vs Extractable Value Gate: If estimated cost to fabricate price move on cheapest agreeing source is lower than the new borrowing capacity unlocked, effective price clamps to min(spot, TWAP, historical band) and Sentinel enters PROTECTIVE.
3. Epoch Loss Budget: Hard ceiling on borrow growth ($50k/epoch) guarantees bounded worst-case loss regardless of whether detection triggers.
4. Vault Integrity Check: Catches bare donation / share inflation attacks (Venus wUSDM/vTHE style) by comparing assets-per-share jumps.
5. Sentinel 6-State Machine: FRESH (100% ceiling), WATCH (80%), PROTECTIVE (30%), STALE (50%), DISPUTED (0%), RECOVERING (25%-75%).

Current Live System State (GROUNDING DATA):
${JSON.stringify(groundedOn, null, 2)}

Formatting Guidelines:
- Format response with clean engineering headers: [QUERY], [ANALYSIS], [RISK ENGINE VERDICT], [LIVE ON-CHAIN EVIDENCE].
- Keep it concise, authoritative, and direct (150-250 words).`;

  try {
    const url = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${GEMINI_API_KEY}`;
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [
          {
            role: "user",
            parts: [{ text: `${systemInstruction}\n\nUser Question: ${query}` }]
          }
        ],
        generationConfig: {
          temperature: 0,
          maxOutputTokens: 2048
        }
      })
    });

    const data = await response.json();
    if (data.candidates && data.candidates[0]?.content?.parts[0]?.text) {
      const text = data.candidates[0].content.parts[0].text;
      return res.json({ answer: text, model: "gemini-2.5-flash", groundedOn });
    } else {
      const errorMsg = data.error?.message || "No response from Gemini API";
      return res.status(500).json({ error: errorMsg, groundedOn });
    }
  } catch (err) {
    console.error("[Gemini API Error]", err);
    return res.status(500).json({ error: err.message, groundedOn });
  }
});

app.listen(PORT, () => {
  console.log(`========================================================`);
  console.log(`  ORIGIN ASO v2 MOCK SOURCES SERVER ON http://localhost:${PORT}`);
  console.log(`  Endpoints:`);
  console.log(`    GET  /sources`);
  console.log(`    POST /sources/:id/simulate-shock`);
  console.log(`    POST /sources/:id/weight`);
  console.log(`    GET  /vault/status`);
  console.log(`    POST /vault/simulate-donation`);
  console.log(`    POST /vault/reset`);
  console.log(`    POST /api/ask`);
  console.log(`========================================================`);
});
