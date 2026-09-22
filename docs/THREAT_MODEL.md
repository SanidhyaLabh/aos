# ORIGIN — Threat Model & Attack Matrix

## 1. Threat Actors & Capabilities

| Threat Actor | Motivation | Capabilities | Primary Defense Layer |
| :--- | :--- | :--- | :--- |
| **Flash-Loan Manipulator** | Instant capital extraction | Uncapped temporary capital within single block; MEV searcher capabilities | Hierarchical EEG token bucket (limits single-block extraction to remaining capacity) |
| **Sybil Attacker** | Evade per-wallet rate limits | Generates 100 to 10,000 distinct Ethereum addresses / contract proxies | Shared Market, Risk-Group, and Global token buckets |
| **Cross-Market Arbitrageur** | Drain liquidity across pools | Moves between RWAUSD, ETH, BTC, and TBILL markets simultaneously | Global Exposure Guard (aggregates gross debt across all markets) |
| **Churn Attacker** | Reset rate limits via cycling | Borrows, repays, and immediately re-borrows in a loop | Anti-Churn Invariant (Repayments do NOT refill the bucket) |
| **Compromised Backend** | Inject false prices / steal funds | Controls off-chain API, signs arbitrary payloads | On-chain signature verification, EIP-712 domain bounds, on-chain divergence bounds, EEG capacity caps |
| **Malicious Attester Key** | Broadcast invalid valuations | Key compromised or stolen | Staked bond slashing, multi-source verification, Sentinel protective trip, multi-attester quorum |
| **Direct Protocol Bypass** | Circumvent BorrowGateway | Calls underlying lending pool contracts directly | Underlying market authorization check (only callable via authorized Gateway) |

---

## 2. Attack Matrix & Verification Strategy

| Attack Vector | Attacker Action | Expected Protocol Behavior | Foundry / Unit Test |
| :--- | :--- | :--- | :--- |
| **1. Mega Flash Drain** | Attacker pumps oracle +1000% and attempts $10M borrow against $100k capacity | Transaction reverts on-chain with `DebtRateLimitExceeded(10M, 100k)` | `test_MegaFlashDrainReverts()` |
| **2. Multi-Wallet Sybil** | Attacker splits $100k borrow into 100 transactions of $1k across 100 wallets | Wallets 1–50 consume bucket; Wallets 51–100 revert with `DebtRateLimitExceeded` | `test_SybilAttackExhaustion()` |
| **3. Cross-Market Migration** | Attacker extracts $400k from RWA, $300k from ETH, $300k from BTC against $1M global cap | Total reaches $1M; any subsequent borrow in ANY market reverts | `test_CrossMarketGlobalCap()` |
| **4. Repayment Churn** | Attacker borrows $50k, repays $50k, attempts to borrow $60k in same block | Repayment burns debt but does not refill bucket; second borrow reverts | `test_RepaymentDoesNotRefill()` |
| **5. Liquidation Churn** | Liquidator liquidates underwater position; attacker attempts immediate borrow | Liquidation burns bad debt but does not restore EEG gross capacity | `test_LiquidationDoesNotRefill()` |
| **6. Direct Protocol Bypass** | Attacker calls `lendingMarket.borrow()` directly bypassing `BorrowGateway` | Transaction reverts with `UnauthorizedGateway()` | `test_DirectBypassReverts()` |
| **7. Replay Attack** | Attacker submits previous valid attestation payload to advance price | Transaction reverts on-chain with `StaleRoundOrNonce()` | `test_ReplayRoundReverts()` |
| **8. Cross-Chain / Domain Replay** | Attacker takes attestation signed for Ethereum Mainnet and submits to Arbitrum | EIP-712 domain separator hash mismatch; reverts with `InvalidSignature()` | `test_WrongChainIdReverts()` |
| **9. Source Divergence Spoof** | Attester submits prices where spread exceeds 50 bps (0.50%) | Smart contract computes divergence on-chain; reverts with `DivergenceExceeded()` | `test_DivergenceReverts()` |
| **10. Insufficient Quorum** | Attester submits payload with only 2 sources when 3 are required | Contract verifies `sources.length >= minSources`; reverts | `test_InsufficientQuorum()` |
| **11. Dependent Sources** | Attester submits 3 sources all owned by same provider | Contract verifies `independentGroups >= minGroups`; reverts | `test_CorrelatedSourcesRejected()` |
| **12. Backend Outage** | Backend server crashes or RPC fails | Smart contracts continue enforcing EEG capacity; oracle transitions to STALE; repayments remain enabled | `test_BackendDowntimeSafety()` |
