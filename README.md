# ORIGIN — Economic Exposure Guard (EEG)

> **On-chain Economic Exposure Guard that limits how quickly a lending market can create new debt, ensuring that even a manipulated oracle cannot be converted into an unlimited instantaneous liquidity drain.**

Active Branch: `feat/economic-exposure-guard`

![Diagram](assets/diagram.png)

---

## The Core Thesis

Oracle manipulation attacks (e.g. Mango Markets, Inverse Finance, Platypus, Venus) become catastrophic when a false or manipulated collateral price can **instantly unlock 100% of the remaining borrowing liquidity** in a lending market within a single transaction.

Instead of trying to prove whether an oracle is "truthful" or "honest" (an undecidable problem under deep manipulation or private mempool attacks), **ORIGIN EEG** enforces a mathematical debt-velocity invariant:

$$\Delta \text{Debt}_{\text{new}} \le \text{Capacity}_0 + R_{\text{max}} \times \Delta t$$

**Meaning:** Aggregate newly originated debt across the entire lending market cannot exceed the configured debt-expansion capacity over time.

---

## Key Architectural Invariants

1. **Token-Bucket Debt Rate Limiter:**
   - `maxCapacity`: Configured burst borrowing allowance (e.g., $\$100,000$).
   - `refillRatePerSecond`: Linear capacity replenishment over time (e.g., $\$25,000$ per 15 minutes = $\$27.78/\text{sec}$).
   - `currentCapacity`: Capacity remaining for new debt creation.
2. **Repayments Do NOT Refill the Bucket (Anti-Churn Invariant):**
   - Repayments reduce user and market debt, but **never increase EEG capacity**.
   - This prevents attackers from looping flash-loan borrows and repayments to bypass the rate limit.
3. **Repayments and Liquidations Are 100% Ungated:**
   - `repay()` and `liquidate()` execute with zero rate-limit checks in all protocol states. Emergency de-leveraging is never throttled.
4. **Seamless Normal UX:**
   - Honest small borrowers (e.g., $\$2,900$) experience zero friction: 1 normal transaction, normal gas, no KYC, no approvals, no keepers.
5. **Sybil & Flash Loan Resistant:**
   - Capacity is market-wide and aggregate. Splitting $\$10\text{M}$ into 100 or 1,000 distinct wallets or contracts hits the exact same shared token bucket.

---

## Quick Start (Windows One-Click Launcher)

Double-click or run:
```bat
run.bat
```
This automatically starts:
1. **Anvil Local EVM Node** on `http://127.0.0.1:8545`
2. **Smart Contracts** (compiled & deployed with EEG integration)
3. **Python Risk Engine Backend** on `http://localhost:5001`
4. **Frontend Interactive Terminal** on `http://localhost:5173/terminal`

---

## 🏛️ System Architecture

```text
[User / Borrower / Attacker]
            │
            ▼
    ToyLendingMarket.sol
            │
      borrow(amount)
            │
            ├─────────────────────────────────────────┐
            ▼                                         ▼
   [Layer 1: Oracle & Collateral]        [Layer 2: ORIGIN EEG Guard]
   • Spotter / Feeds / Twap              • EconomicExposureGuard.sol
   • Collateral Ratio Check              • replenish() over Δt
            │                            • amount <= currentCapacity?
            │                                  ├── YES → consumeCapacity()
            │                                  └── NO  → REVERT on-chain
            ▼                                         │
   [Layer 3: Debt Accounting] ◄───────────────────────┘
   • positions[user].debt += amount
   • totalDebt += amount
```

---


##  Resolving the Fundamental Trade-Off: Seamless UX vs. Exploit Prevention

A core debate in DeFi protocol design is the friction trade-off:
> *"Does protecting against catastrophic exploits require sacrificing composability, liquidity velocity, and user convenience?"*

Traditional mitigations force painful compromises:
- **Emergency Circuit Breakers & Pauses**: Freeze the entire protocol, locking legitimate users out of their funds and disabling liquidations when market volatility is highest.
- **Withdrawal / Borrow Timelocks & Queues**: Force honest users to wait hours or days for routine actions, destroying instant composability and arbitrage.
- **Heavyweight Governance Multisigs**: Introduce centralized human latency and censorship risks into permissionless protocols.

**ORIGIN EEG breaks this false dichotomy** through five foundational design principles:

### 1. Exploiting Time-Scale Asymmetry (The Core Insight)
Flash-loan oracle manipulation attacks and normal borrowing have opposite temporal requirements:
- **The Attacker:** Requires **instantaneous execution within 1 block** (or few seconds). If the attacker cannot extract millions immediately, arbitrageurs, liquidation bots, or fresh oracle price updates close the pricing discrepancy, destroying the profitability of the attack.
- **Honest Borrowers:** Operate over **hours, days, and weeks**. Real credit demand is distributed continuously across time and users.

By bounding instantaneous debt origination ($\text{Burst Cap} = \$100,000$) while allowing continuous linear refill ($\$25,000 / 15\text{ min}$), ORIGIN renders multi-million-dollar economic attacks economically irrational, without capping total long-term borrowing volume.

### 2. Decoupling Burst Ceiling from Total Market Throughput
Rate limiting does **not** mean low borrowing throughput:
$$\text{Daily Debt Origination Throughput} = \$100,000 + \left(\frac{\$25,000}{900\text{ s}} \times 86,400\text{ s}\right) = \mathbf{\$2,500,000 \text{ per day}}$$
- Honest volume of **$2.5M/day** flows freely without governance intervention or delays.
- Maximum instantaneous single-block loss under a 100% compromised oracle is strictly bounded to **$\le \$100,000$**.

### 3. Invisible, Frictionless UX for Everyday Borrowers
For $99.9\%$ of legitimate borrowers (e.g., retail loans of $\$1,000$ to $\$25,000$):
- **1 Standard Transaction**: No multi-step approval, timelock, or multi-signature delays.
- **Minimal Gas Overhead**: The token-bucket update executes in pure integer arithmetic on an updated timestamp and capacity variable (`~5,200` additional EVM gas, or `<3%` of standard borrow gas).
- **Zero Keeper Dependency**: No off-chain bot or keeper needs to be paid or trusted to pump or maintain the rate limiter.

### 4. Zero-Cost Reversion Protection (Pre-Flight Simulation)
If an unusual surge or an attacker exhausts current capacity:
- dApps and frontends query `eeg.getAvailableCapacity()` via gasless `eth_call`.
- The user's interface displays the available credit allowance and precise seconds until the next refill.
- Users are proactively warned *before* signing, preventing failed on-chain transactions and wasted gas fees.

### 5. Asymmetric Friction: The Anti-Churn Invariant
Friction in ORIGIN is strictly one-directional:
- **Debt Creation (`borrow`)** is velocity-bounded by EEG.
- **Debt Reduction (`repay`)** is **100% UNGATED and zero-friction** in every protocol state.
- **De-leveraging and Liquidations** never hit the rate limiter, ensuring protocol solvency during market crashes.
- **Anti-Churn Invariant**: Repayments *do not* refill the token bucket. This ensures an attacker cannot take out flash loans, repay them, and churn capacity to game the system.

---

## Quantitative Manipulation-Cost Estimation Theorem (Risk & Liquidation Layer)

In addition to token-bucket rate limiting, the underlying **Risk Engine** evaluates whether an economic exploit is mathematically profitable under current market liquidity.

### 1. The Fundamental Economic Exposure Bound

ORIGIN does not assume that oracle manipulation is impossible or economically irrational. Instead, it establishes a hard upper bound on the amount of new debt that can be created through the protected borrowing path, regardless of the oracle-reported price:

$$
\Delta Debt_{\text{new}} \le C_{\max} + R\Delta t
$$

Where:

- $C_{\max}$: maximum burst capacity available for new borrowing.
- $R$: debt issuance refill rate per unit of time.
- $\Delta t$: elapsed time since the relevant capacity was consumed.
- $\Delta Debt_{\text{new}}$: cumulative new debt created through the protected path during that interval.

Therefore, even if an attacker manipulates the collateral price upward, uses flash loans, creates multiple accounts, or submits many transactions, the maximum additional debt that can be created is bounded by the configured exposure budget:

$$
E_{\text{borrow}}(T) \le C_{\max} + R T
$$

This bound is independent of the number of attackers, accounts, transactions, or the oracle's reported value. ORIGIN therefore does not claim to prevent oracle manipulation or guarantee zero loss; instead, it prevents an oracle failure from producing unlimited new economic exposure and gives the protocol a bounded response window.

For an assumed incident response window $T$:

$$
E_{\text{borrow,max}}(T) = C_{\max} + RT
$$

If the protocol configures $C_{\max}$ and $R$ such that:

$$
C_{\max} + RT \le B_{\text

### 2. Multi-Source Liquidity & Coalition Cost Derivation

#### Step 1: Capital to Push an Individual Source ($C_{\text{cap}, s}$)
For any tradable market venue $s$ with quote depth $R_s$ under a constant-product or orderbook market model:
$$C_{\text{cap}, s}(m) = R_s \cdot (\sqrt{1 + m} - 1)$$
*(For linear orderbook depth approximations: $C_{\text{cap}, s}(m) = D_s \cdot m$, where $D_s$ is the capital required to move the price $1\%$.)*  
For untradable reference rates (e.g., Fed H.15, regulatory indices): $C_{\text{cap}, s}(m) = \infty$.

#### Step 2: Coalition Cost to Move the Weighted Median ($C_{\text{cap, med}}$)
Let reporting sources have normalized weights:
$$w'_s = \frac{w_s}{\sum_{j \in \text{Reporting}} w_j}$$
To shift the median price by $+m\%$, the attacker must manipulate a subset of sources $S$ whose cumulative weight crosses the $50\%$ consensus threshold. The minimum capital required across all feasible corruptible coalitions is:
$$C_{\text{cap, med}}(m) = \min_{S \subseteq \text{Sources}} \left\{ \sum_{s \in S} C_{\text{cap}, s}(m) \quad \text{s.t.} \quad \sum_{s \in S} w'_s \ge 0.5 \right\}$$
*(Sources sharing the same upstream aggregator or feed are grouped together to prevent correlated sybil manipulation.)*

#### Step 3: Net Capital Loss After Position Unwind ($C_{\text{net}}$)
An attacker cannot recover 100% of their capital after pumping an illiquid market. Unwinding the position incurs severe slippage, MEV arbitrage losses, and trading fees:
$$C_{\text{net}}(m) = \rho \cdot C_{\text{cap, med}}(m)$$
Where $\rho$ is the empirically calibrated net-loss ratio ($\rho \approx 0.15$ to $0.50$ depending on pool depth and arbitrage velocity).

---

### 3. Extractable Unbacked Debt ($E_{\text{borrow}}$)
When the oracle price is inflated by $+m\%$, the attacker posts collateral with true value $V$ and borrows against the inflated valuation $V \cdot (1 + m)$:
$$E_{\text{borrow}}(m) = \text{LTV} \cdot V \cdot m$$
Or expressed as a function of the available market debt headroom $H$ and liquidation threshold $\text{mat}$:
$$E_{\text{borrow}}(m) = H \cdot \max\left(0, 1 - \frac{\text{mat}}{1 + m}\right)$$

---

### 4. Dynamic Cost-Anchored Debt Ceiling ($\Gamma$)
To guarantee bounded protocol risk across all possible manipulation magnitudes $m \le m_{\text{ref}}$, the Risk Engine enforces a dynamic debt ceiling:
$$\Gamma = k \cdot \frac{C_{\text{net}}(m_{\text{ref}})}{m_{\text{ref}}}$$
Where:
- $m_{\text{ref}}$: The maximum reference price surge defended (e.g., $15\%$).
- $k$: Governance safety factor ($k \le 0.10$, chosen strictly below the 5th-percentile loss ratio).

The effective borrowing ceiling and epoch growth limit are then bounded dynamically:
$$\text{DebtCeiling} = \min\left(\text{ConfiguredCeiling}, \; \Gamma\right)$$
$$\text{EpochGrowthCap} = g \cdot \Gamma \quad (g \approx 20\%)$$

---

### 5. Closing Structural Vulnerabilities (Anti-Exploit Invariants)
1. **Slow-Ratchet Defense:** Price inflation $m$ is measured not only against the last spot update, but against a 24-hour slow exponential moving anchor with an absolute drift cap per epoch ($100\text{ bps/epoch}$), eliminating multi-day creeping manipulation.
2. **Fake-Depth Defense:** Rather than reading spot liquidity (which an attacker could temporarily spoof via flash loans or wash trading), $\Gamma$ is calculated using the **minimum depth** observed across the last $N$ epochs (12-cycle ring buffer in `RiskEngine.sol`).
3. **Dual-Horizon Friction (DHFE):** For large borrowers attempting to consume remaining capacity near $\Gamma$, a convex friction multiplier $\phi(u) = u^{k_\phi}$ dynamically raises borrow interest rates, rendering rapid capital accumulation prohibitive.

---

## Prior Art Matrix

| System | Mechanism | Global / Per-User | Time-Based | Borrow Specific | Oracle Dependent | Aggregate | Similarity to EEG |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **ERC-7265** | Outflow circuit breaker | Vault / Global | Yes | No (Withdrawals) | No | Yes | Medium (Protects exits, not debt creation) |
| **Aave V3 Caps** | Static debt ceiling ($D \le \text{Cap}$) | Market / Global | No (Governance) | Yes | No | Yes | Low (Static cap, no continuous refill rate) |
| **Maker/Sky D3M** | Dynamic debt ceilings | Protocol / Line | Governance/GSM | Yes | Partially | Yes | Medium (Heavyweight governance adjustments) |
| **Fluid (Instadapp)**| Rate limits on operations | Pool / Global | Yes | Yes (B&W) | No | Yes | High (Similar token bucket philosophy) |
| **Euler V2** | Dynamic borrow limits | Vault / Global | Yes | Yes | No | Yes | High (Rate limits on credit lines) |
| **ORIGIN EEG** | **Debt Expansion Token Bucket** | **Market-wide** | **Yes (Continuous)**| **Yes (Borrow only)**| **No** | **Yes** | **Targeted Primitive** |

### Classification: **Composition of Known Primitives with Differentiated DeFi Invariants**
- Prior art in ERC-7265 primarily addresses **withdrawal drains** (vault exits).
- Aave borrow caps address **absolute static ceilings**.
- ORIGIN EEG addresses **debt creation velocity** ($\Delta \text{Debt} / \Delta t$) during oracle failure, ensuring repayment anti-churn guarantees and frictionless normal user flows.

---

## Test Suite & Invariants

Foundry test contract: [`test/EconomicExposureGuard.t.sol`](file:///c:/Users/Sanidhya-PC/OneDrive/Desktop/Multipli/test/EconomicExposureGuard.t.sol)  
On-Chain Anvil suite: [`test/test_eeg_onchain.js`](file:///c:/Users/Sanidhya-PC/OneDrive/Desktop/Multipli/test/test_eeg_onchain.js)

Run on-chain validation:
```bash
node test/test_eeg_onchain.js
```
**Results:**
- `[PASS] Test 1: Normal $2,900 borrow executes cleanly in 1 tx`
- `[PASS] Test 2: $10,000,000 exploit borrow reverts on-chain`
- `[PASS] Test 3: Sybil attack (4 wallets) hits aggregate capacity ceiling`
- `[PASS] Test 4: Time warp +15 min refills capacity linearly (+$25,000)`
- `[PASS] Test 5: Repayment is ungated and does NOT refill capacity`

---

## Claims & Non-Claims

### What We Defensibly Claim
- **Bounded Debt Velocity:** Assuming all borrow paths route through EEG, aggregate newly originated debt cannot exceed $\text{Capacity}_0 + R_{\text{max}} \times \Delta t$.
- **Zero Friction for Normal Borrowers:** Small, everyday borrows within capacity require no extra user approval, no multi-tx flow, and zero additional signatures.
- **Oracle-Agnostic Defense:** Does not depend on the oracle being truthful or unmanipulated.

### What We Explicitly Do NOT Claim
- ❌ *"ORIGIN solves all oracle manipulation"* (oracle prices can still move; we only bound credit creation velocity).
- ❌ *"ORIGIN guarantees zero bad debt"* (existing loans can still become undercollateralized if real market prices collapse).
- ❌ *"ORIGIN eliminates MEV"* (bots can compete for available capacity when a bucket is near empty).
- ❌ *"Parameters are mathematically optimal"* (capacity and refill rates are demo/governance policy assumptions).

---

## 📜 License
Apache 2.0 / MIT — Developed for Multipli Hackathon 2026.
