# ORIGIN — Security Model & Invariants

## 1. Security Philosophy: Bounded Economic Consequence

Traditional DeFi security relies almost entirely on the **Truth Assumption**: that if an oracle is sufficiently decentralized or delayed (e.g. Maker OSM, Chainlink DON), the price reported to smart contracts will always be accurate.

However, historical exploit analysis demonstrates that under conditions of extreme market volatility, low DEX liquidity, cross-chain bridge failures, or private mempool bribe attacks, the Truth Assumption routinely fails. When an incorrect or manipulated valuation reaches a lending pool, an attacker can extract 100% of available protocol liquidity in a single block.

ORIGIN introduces a dual paradigm:
1. **Maximize Valuation Integrity** via ASO (multi-source attestations, divergence checks, strict freshness).
2. **Mathematically Bound Exploitation Consequence** via Hierarchical EEG (token-bucket gross-issuance limits).

```
   Valuation Uncertainty   ×   Bounded Gross Issuance   =   Strictly Contained Loss
```

---

## 2. Core Mathematical Invariants

### Invariant 1: Market Gross-Issuance Bound
For any market $m$, newly originated gross debt over any time window $[t_1, t_2]$ cannot exceed the available capacity plus the time-integral of the refill rate:
$$\Delta \text{Debt}_m(t_1, t_2) \le C_m(t_1) + R_m \cdot (t_2 - t_1)$$
where $C_m(t) \le C_{m,\text{max}}$ at all times $t$.

### Invariant 2: Risk-Group Gross-Issuance Bound
For any correlated risk group $G$ containing markets $\{m_1, m_2, \dots, m_k\}$:
$$\sum_{m \in G} \Delta \text{Debt}_m(t_1, t_2) \le C_G(t_1) + R_G \cdot (t_2 - t_1)$$

### Invariant 3: Global Gross-Issuance Bound
Across all markets $\mathcal{M}$ in the entire protocol:
$$\sum_{m \in \mathcal{M}} \Delta \text{Debt}_m(t_1, t_2) \le C_{\text{global}}(t_1) + R_{\text{global}} \cdot (t_2 - t_1)$$

### Invariant 4: Sybil & Identity Independence
The capacity consumption of a debt origination depends exclusively on the gross amount borrowed $\Delta D$, regardless of the number of unique Ethereum addresses $N_{\text{wallets}}$ used:
$$\text{CapacityConsumed}\left(\sum_{i=1}^N \Delta D_i\right) \equiv \sum_{i=1}^N \text{CapacityConsumed}(\Delta D_i)$$
Partitioning a $\$100,000$ borrow across 100 addresses exhausts the exact same $\$100,000$ of bucket capacity as a single borrow from 1 address.

### Invariant 5: Anti-Churn (Zero Repayment Refill)
Repayments reduce user debt and protocol liabilities, but **never increase EEG bucket capacity**:
$$\frac{\partial C(t)}{\partial \text{Repayment}} \equiv 0$$
$$\frac{\partial C(t)}{\partial \text{Liquidation}} \equiv 0$$
Only elapsed block time replenishes capacity:
$$\frac{dC}{dt} = R, \quad \text{for } C < C_{\text{max}}$$

### Invariant 6: Ungated De-leveraging
The operations `repay()` and `liquidate()` must execute without rate limits, gating, or dependency on backend availability across **all** protocol states (`NORMAL`, `DEGRADED`, `GUARDED`, `BLOCKED`).

### Invariant 7: Atomic Multi-Tier Consumption
Every borrow transaction must consume capacity in the Market, Risk Group, and Global buckets within the **same atomic transaction**. If any single tier has insufficient capacity:
$$\text{AvailableCapacity} < \text{RequestedAmount} \implies \text{REVERT}$$
State changes across all tiers are completely rolled back upon revert.

### Invariant 8: Monotonic Nonce & Replay Resistance
An attestation payload $\mathcal{A}$ signed by an authorized attester is valid only once for a specific tuple $(\text{chainId}, \text{verifyingContract}, \text{assetId}, \text{roundId})$:
$$\text{roundId}_{\text{new}} = \text{roundId}_{\text{last}} + 1$$
Any submission where $\text{roundId} \le \text{roundId}_{\text{last}}$ must revert on-chain.

### Invariant 9: Source Quorum & Group Independence
An attestation is accepted on-chain if and only if:
$$N_{\text{sources}} \ge N_{\text{min}} \quad \land \quad N_{\text{independent\_groups}} \ge G_{\text{min}}$$
where sources sharing an upstream feed or infrastructure provider map to the same group identifier.

### Invariant 10: Strict Freshness & Sampling Window
An attestation is accepted on-chain if and only if:
$$\text{block.timestamp} \ge T_{\text{windowEnd}}$$
$$\text{block.timestamp} - T_{\text{windowEnd}} \le \text{maxStaleness}$$
$$T_{\text{windowEnd}} - T_{\text{windowStart}} \le \text{maxWindow}$$

---

## 3. Explicit Security Boundaries: What ORIGIN Does NOT Solve

To maintain clear engineering scope and avoid false security promises, ORIGIN explicitly documents its boundaries:

1. **Oracle Manipulation Itself**: ORIGIN does not magically eliminate off-chain price manipulation on low-liquidity exchanges. Instead, it prevents that manipulated price from extracting unlimited debt before the market can correct.
2. **Existing Bad Debt**: If bad debt already exists in a market prior to an oracle failure, EEG does not eliminate the shortfall; it prevents new bad debt from being created.
3. **Liquidation Economics**: EEG protects borrow origination. Secondary market liquidation profitability depends on collateral market depth and liquidator participation.
4. **Legitimate Users During Emergency States**: In `GUARDED` or `BLOCKED` states, legitimate borrowers may be temporarily rate-limited or paused. De-leveraging and repayments remain unaffected.
5. **Private Key / Governance Compromise**: If protocol governance keys are compromised, on-chain timelocks delay malicious parameter expansion, but ultimate defense requires multisig / DAO governance security.
