# ORIGIN — System Architecture Document

## 1. System Mission & Philosophy

ORIGIN is an oracle-agnostic economic risk-containment layer designed for Real World Asset (RWA) and Decentralized Finance (DeFi) lending protocols.

The system addresses a fundamental limitation in DeFi security:
> **Oracles answer "What is this asset worth?" but cannot answer "How much new debt should the protocol allow this price to create if the valuation is compromised?"**

ORIGIN establishes a defense-in-depth security model across three synchronized layers:
1. **ASO (Attested Staleness Oracle)**: Verifies cryptographic validity, multi-source independence, freshness, and low divergence before a valuation is ingested.
2. **SENTINEL (Deterministic Risk State Management)**: Evaluates protocol, oracle, and debt velocity telemetry to transition deterministically between discrete states: `NORMAL`, `DEGRADED`, `GUARDED`, and `BLOCKED`.
3. **EEG (Hierarchical Economic Exposure Guard)**: Enforces hard mathematical bounds on gross debt origination across local markets, risk groups, and the global protocol, ensuring that even a completely falsified valuation cannot trigger an instantaneous liquidity drain.

---

## 2. High-Level Architecture Diagram

```text
                                EXTERNAL DATA LAYER
                                         │
        ┌────────────────────────────────┼────────────────────────────────┐
        ▼                                ▼                                ▼
  Chainlink Aggregators         RWA Custodian / NAV              Exchange APIs
  (On-Chain / Off-Chain)        (Ondo, Securitize, etc.)         (Coinbase, Kraken)
        │                                │                                │
        └────────────────────────────────┼────────────────────────────────┘
                                         ▼
                            DATA NORMALIZATION ENGINE
                          (Units, Wad Precision, Times)
                                         │
                                         ▼
                                ASO ORACLE ENGINE
                    (Independence, Freshness, Divergence Checks)
                                         │
                                         ▼
                                ATTESTATION ENGINE
                           (EIP-712 Structured Signing)
                                         │
                                         ▼
                              SMART CONTRACTS BOUNDARY
═══════════════════════════════════════════════════════════════════════════════════
                                         │
                                         ▼
                                  ASO ADAPTER
                      (On-Chain EIP-712 & Quorum Verification)
                                         │
                                         ▼
                                 SENTINEL REGISTRY
                       [NORMAL → DEGRADED → GUARDED → BLOCKED]
                                         │
                                         ▼
                            GLOBAL EXPOSURE GUARD (EEG)
                                         │
              ┌──────────────────────────┴──────────────────────────┐
              ▼                                                     ▼
     RWA RISK-GROUP GUARD                                CRYPTO RISK-GROUP GUARD
              │                                                     │
       ┌──────┴──────┐                                       ┌──────┴──────┐
       ▼             ▼                                       ▼             ▼
  RWAUSD EEG     TBILL EEG                                ETH EEG       BTC EEG
       │             │                                       │             │
       └─────────────┴───────────────────┬───────────────────┴─────────────┘
                                         │
                                         ▼
                                   BORROW GATEWAY
                                 (Single Atomic Tx)
                                         │
                                         ▼
                              UNDERLYING LENDING POOLS
```

---

## 3. Core Architectural Principle: Intelligence vs. Enforcement

A central invariant of ORIGIN is the strict separation between off-chain computation and on-chain authority:

- **The Backend provides Intelligence**:
  - Ingests high-frequency feeds.
  - Normalizes decimal precisions and timestamps.
  - Aggregates multi-source feeds into liquidity-weighted consensus valuations.
  - Quantifies market manipulation costs ($C_{\text{cap}}(m)$) and debt velocity.
  - Monitors mempool and pending blocks.
  - Formats and signs EIP-712 cryptographic attestation packages.

- **The Smart Contracts provide Enforcement**:
  - Independently verify signatures, chain IDs, contract addresses, and monotonic round nonces.
  - Independently verify source counts, independent groups, and price spread bounds.
  - Independently track token-bucket state over elapsed block timestamps.
  - Enforce atomic capacity consumption across Market $\to$ Risk-Group $\to$ Global buckets.
  - Revert any transaction that exceeds capacity or violates Sentinel policies.

> **Failure Safety**: If the backend crashes, becomes unresponsive, or is compromised, on-chain contracts fail closed for debt expansion: existing prices become stale, capacity continues to bound origination, and ungated de-leveraging (repayments, liquidations) remains fully operational.

---

## 4. Subsystem Specifications

### 4.1 ASO (Attested Staleness Oracle)
- **Attestation Struct**: EIP-712 compliant data structure carrying asset ID, consensus price, observation array (source ID, individual price, timestamp), window boundaries (`windowStart`, `windowEnd`), round ID, and signature.
- **On-Chain Verification**:
  1. $T_{\text{now}} - T_{\text{windowEnd}} \le \text{maxStaleness}$.
  2. $T_{\text{windowEnd}} - T_{\text{windowStart}} \le \text{maxSamplingWindow}$ (anti-cherry-picking).
  3. $N_{\text{sources}} \ge \text{MIN\_SOURCES}$ and $N_{\text{groups}} \ge \text{MIN\_INDEPENDENT\_GROUPS}$.
  4. $\frac{P_{\text{max}} - P_{\text{min}}}{P_{\text{consensus}}} \le \text{MAX\_DIVERGENCE\_BPS}$.
  5. Monotonic nonces prevent round replays across chains and contracts.

### 4.2 Sentinel Registry
- **States**:
  - `NORMAL`: All feeds healthy; standard borrowing limits and standard EEG refill rates.
  - `DEGRADED`: Minor feed dropout or elevated divergence; reduced debt ceilings and throttled EEG refills.
  - `GUARDED`: Severe divergence, abnormal debt velocity, or cost-gate warning; highly restricted borrowing capacity.
  - `BLOCKED`: Oracle stale, consensus failure, or emergency trip; **gross new borrowing = $0$**.
- **Invariant**: Ungated de-leveraging: Repayments (`repay`) and liquidations (`liquidate`) are **never blocked** regardless of Sentinel state.

### 4.3 Hierarchical EEG (Economic Exposure Guard)
- **Mathematical Invariant**:
  $$\Delta \text{Debt}_{\text{new}}(t_1, t_2) \le C_0 + \int_{t_1}^{t_2} R(t)\,dt$$
- **Three-Tier Containment**:
  1. **Market EEG**: Restricts burst borrowing and velocity for a specific collateral/debt market pair.
  2. **Risk-Group EEG**: Restricts aggregate debt expansion across correlated asset classes (e.g., all RWA private credit, or all long-tail crypto tokens).
  3. **Global EEG**: Restricts total protocol-wide credit expansion across all markets simultaneously.
- **Consumption Invariant**: A valid borrow must consume capacity in Market, Risk Group, and Global buckets in a single atomic transaction. If any bucket has insufficient capacity, the entire transaction reverts.
- **Anti-Churn Invariant**: Repayments and liquidations do **NOT** refill the token bucket. Only elapsed time refills capacity at rate $R$.

### 4.4 Borrow Gateway
- Serves as the primary public entry point for credit origination.
- Checks `IOriginOracle` price and freshness.
- Inspects Sentinel state.
- Executes atomic three-tier capacity consumption.
- Dispatches borrow instruction to underlying market.
- Disallows re-entrancy and partial execution.

---

## 5. Technology Stack

- **Smart Contracts**: Solidity ^0.8.20 (Foundry toolchain).
- **Backend Service**: Python 3.11+, FastAPI (REST + WebSockets), Web3.py, Pydantic v2, SQLAlchemy.
- **Data Stores**:
  - **PostgreSQL**: Durable event logs, historical attestations, transaction receipts, audit snapshots.
  - **Redis**: Real-time price cache, distributed locks, WebSocket pub/sub bus.
- **Frontend Dashboard**: Real-time operations console displaying live Sentinel states, hierarchical bucket levels, and oracle telemetry.
