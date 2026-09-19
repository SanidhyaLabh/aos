// SPDX-License-Identifier: MIT
/**
 * @file attestationService.js
 * @notice Off-chain Attestation Engine for Attested Staleness Oracle (ASO).
 * Samples N >= 3 independent feeds, enforces divergence threshold, and signs ECDSA attestations.
 */

import { ethers } from "ethers";

export const DEFAULT_SOURCES = [
  {
    id: "0x1111111111111111111111111111111111111111",
    name: "Ondo / Securitize RWA Custodian Yield Feed",
    type: "Institutional Custodian",
    basePrice: 100.0,
    jitterStdDev: 0.05,
    status: "HEALTHY",
    latencyMs: 42
  },
  {
    id: "0x2222222222222222222222222222222222222222",
    name: "Coinbase Prime Institutional Index",
    type: "CEX Reference",
    basePrice: 100.02,
    jitterStdDev: 0.08,
    status: "HEALTHY",
    latencyMs: 28
  },
  {
    id: "0x3333333333333333333333333333333333333333",
    name: "Kraken Treasury & FX Benchmark Rate",
    type: "FX / Benchmark",
    basePrice: 99.98,
    jitterStdDev: 0.06,
    status: "HEALTHY",
    latencyMs: 35
  },
  {
    id: "0x4444444444444444444444444444444444444444",
    name: "Fed H.15 / Multipli Interbank Feed",
    type: "Sovereign Yield",
    basePrice: 100.01,
    jitterStdDev: 0.04,
    status: "HEALTHY",
    latencyMs: 65
  }
];

export class AttestationService {
  constructor(options = {}) {
    // Default signer with fixed reproducible private key for demo / testing
    this.signerKey = options.signerKey || "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d";
    this.wallet = new ethers.Wallet(this.signerKey);
    this.chainId = options.chainId || 31337n;
    this.adapterAddress = options.adapterAddress || "0x9fE46736679d2D9a65F0992F2272dE9f3c7fa6e0";
    this.maxDivergenceBps = options.maxDivergenceBps || 50; // 50 bps = 0.50%
    this.sources = JSON.parse(JSON.stringify(DEFAULT_SOURCES));
  }

  getSignerAddress() {
    return this.wallet.address;
  }

  /**
   * Samples active sources with realistic jitter or custom overrides.
   */
  sampleSources(overrides = {}) {
    const now = Math.floor(Date.now() / 1000);
    const windowStart = now - 5; // 5-second sampling window
    const windowEnd = now;

    const samples = this.sources.map((src, index) => {
      let price = src.basePrice;
      if (overrides.prices && overrides.prices[src.id] !== undefined) {
        price = overrides.prices[src.id];
      } else if (overrides.marketPrice !== undefined) {
        // Apply market price baseline with slight natural jitter
        const jitter = (Math.random() - 0.5) * (src.jitterStdDev || 0.05);
        price = Number((overrides.marketPrice + jitter).toFixed(4));
      } else {
        const jitter = (Math.random() - 0.5) * (src.jitterStdDev || 0.05);
        price = Number((src.basePrice + jitter).toFixed(4));
      }

      const isOffline = overrides.offlineSources && overrides.offlineSources.includes(src.id);
      return {
        id: src.id,
        name: src.name,
        type: src.type,
        price,
        timestamp: windowStart + Math.floor(Math.random() * (windowEnd - windowStart + 1)),
        latencyMs: Math.floor(src.latencyMs + (Math.random() * 10 - 5)),
        status: isOffline ? "OFFLINE" : "HEALTHY"
      };
    });

    return { samples, windowStart, windowEnd };
  }

  /**
   * Evaluates consensus across healthy sources.
   * If divergence exceeds maxDivergenceBps or fewer than 3 sources are healthy, returns rejection.
   */
  evaluateConsensus(samples, windowStart, windowEnd) {
    const healthySamples = samples.filter(s => s.status === "HEALTHY");

    if (healthySamples.length < 3) {
      return {
        success: false,
        reason: `Insufficient healthy sources: got ${healthySamples.length}, required >= 3`,
        healthyCount: healthySamples.length,
        samples
      };
    }

    const prices = healthySamples.map(s => s.price).sort((a, b) => a - b);
    const minPrice = prices[0];
    const maxPrice = prices[prices.length - 1];

    // Compute median
    const mid = Math.floor(prices.length / 2);
    const medianPrice = prices.length % 2 !== 0 ? prices[mid] : (prices[mid - 1] + prices[mid]) / 2;

    const spread = maxPrice - minPrice;
    const divergenceBps = Math.round((spread / medianPrice) * 10000);

    if (divergenceBps > this.maxDivergenceBps) {
      return {
        success: false,
        reason: `Consensus divergence ${divergenceBps} bps exceeds maximum tolerance of ${this.maxDivergenceBps} bps`,
        divergenceBps,
        minPrice,
        maxPrice,
        medianPrice,
        samples
      };
    }

    return {
      success: true,
      price: medianPrice,
      minPrice,
      maxPrice,
      divergenceBps,
      sources: healthySamples.map(s => s.id),
      windowStart,
      windowEnd,
      samples
    };
  }

  /**
   * Computes struct hash and signs the attestation using ECDSA.
   */
  async buildAndSignAttestation(consensusData, customSigner = null) {
    if (!consensusData.success) {
      throw new Error(`Cannot sign failed consensus: ${consensusData.reason}`);
    }

    const priceWei = ethers.parseEther(consensusData.price.toFixed(6));
    const minPriceWei = ethers.parseEther(consensusData.minPrice.toFixed(6));
    const maxPriceWei = ethers.parseEther(consensusData.maxPrice.toFixed(6));
    const sources = consensusData.sources;
    const windowStart = BigInt(consensusData.windowStart);
    const windowEnd = BigInt(consensusData.windowEnd);

    // Compute keccak256(abi.encodePacked(sources)) matching Solidity
    const sourcesHash = ethers.solidityPackedKeccak256(
      ["address[]"],
      [sources]
    );

    // Compute struct hash matching ASOAdapter.sol:
    // keccak256(abi.encode(price, minPrice, maxPrice, sourcesHash, windowStart, windowEnd, chainId, adapterAddress))
    const abiCoder = ethers.AbiCoder.defaultAbiCoder();
    const encodedStruct = abiCoder.encode(
      ["uint256", "uint256", "uint256", "bytes32", "uint256", "uint256", "uint256", "address"],
      [priceWei, minPriceWei, maxPriceWei, sourcesHash, windowStart, windowEnd, this.chainId, this.adapterAddress]
    );
    const structHash = ethers.keccak256(encodedStruct);

    // Sign Ethereum Signed Message
    const signer = customSigner || this.wallet;
    const signature = await signer.signMessage(ethers.getBytes(structHash));

    return {
      struct: {
        price: priceWei,
        minPrice: minPriceWei,
        maxPrice: maxPriceWei,
        sources,
        windowStart,
        windowEnd,
        signature
      },
      meta: {
        priceNumeric: consensusData.price,
        minPriceNumeric: consensusData.minPrice,
        maxPriceNumeric: consensusData.maxPrice,
        divergenceBps: consensusData.divergenceBps,
        structHash,
        signerAddress: signer.address,
        timestamp: Math.floor(Date.now() / 1000)
      }
    };
  }
}
