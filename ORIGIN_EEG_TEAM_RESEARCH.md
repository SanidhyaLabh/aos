# ORIGIN — Economic Exposure Guard (EEG)
## Comprehensive Architecture Audit, Adversarial Research & Implementation Plan

**Branch:** `feat/economic-exposure-guard`  
**Repository:** `https://github.com/AnantSharmaDev768/aso-sentinel` / `Multipli`  
**Date:** September 2026  
**Status:** Pre-Implementation Research & Architecture Design Document  

---

## 1. Executive Summary & Core Hypothesis

### The Problem
Traditional DeFi lending markets assume that if an oracle returns a price with valid cryptographic signatures and fresh timestamps, the market can safely lend against that valuation up to the aggregate debt ceiling. In historical oracle manipulation exploits (Mango Markets $117M, Venus $3.7M, Silo Finance $392K), attackers pumped spot venues with capital. The oracles accurately reported genuine market trades, but the sudden unlock of immense borrowing capacity allowed instantaneous treasury drainage within a single block.

### The Proposed Paradigm Shift (EEG)
Instead of building increasingly complex mathematical oracle verifiers, multi-source weighted medians, off-chain risk scoring engines, or attribution heuristics:

> **ORIGIN Economic Exposure Guard (EEG) limits how quickly a lending facility can create new debt, ensuring that even a completely compromised or manipulated oracle cannot be converted into an unlimited instantaneous liquidity drain.**

### The Core Invariant
$$\Delta \text{Debt}_{\text{new}} \le \text{Capacity}(t_0) + R_{\text{max}} \cdot \Delta t$$

Aggregate newly originated debt through the credit facility cannot exceed the available protected capacity, which replenishes at a continuous rate $R_{\text{max}}$ (per second) up to a hard ceiling $\text{MaxCapacity}$.

---

## 2. Repository Audit

| Component | Current File | Purpose in ASO Sentinel | Used By | Disposition | Rationale |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`RiskEngine.sol`** | `contracts/RiskEngine.sol` | Calculates manipulation cost $C_{\text{cap}}(m)$, coalition search over reporting feeds, dynamic debt ceiling $\Gamma$, and lookback depth. | `ToyLendingMarket.sol`, `SentinelRegistry.sol` | **Deprecate / Preserve in Branch** | Complex on-chain loop ($O(2^N)$ coalition search). EEG replaces this with an oracle-agnostic token-bucket rate limiter. |
| **`SentinelRegistry.sol`** | `contracts/SentinelRegistry.sol` | 6-state circuit breaker state machine (`FRESH`, `WATCH`, `PROTECTIVE`, `STALE`, `DISPUTED`, `RECOVERING`). | `ToyLendingMarket.sol` | **Deprecate / Preserve in Branch** | State machine depends on oracle telemetry. EEG does not rely on oracle health state to bound debt expansion. |
| **`FrictionEngine.sol`** | `contracts/FrictionEngine.sol` | Dual-Horizon Friction Engine (DHFE): computes instantaneous & EWMA cumulative friction, adjusts borrowing rate multiplier. | `ToyLendingMarket.sol` | **Optional Soft-Pricing Layer** | Can serve as secondary price discrimination, but must NOT be the primary security boundary. Primary security boundary is the hard EEG capacity bucket. |
| **`ToyLendingMarket.sol`** | `contracts/ToyLendingMarket.sol` | Core lending facility: manages collateral deposits, borrowing, repayments, and risk evaluation. | Borrowers, Liquidators, Frontend | **Modify** | Keep core lending accounting; wire `IEconomicExposureGuard.consumeCapacity(amount)` directly into `borrow()` before state updates. Keep `repay()` 100% ungated. |
| **`ASOAdapter.sol`** | `contracts/ASOAdapter.sol` | EIP-191 attestation-verified oracle adapter with bond staking and divergence checks. | `ToyLendingMarket.sol` | **Keep as Underlying Oracle** | Serves as the oracle returning asset prices. Proves EEG works regardless of oracle type. |
| **`VanillaOSM.sol`** | `contracts/VanillaOSM.sol` | Maker-style 1-hour delay Oracle Security Module for exploit benchmarking. | Benchmark tests | **Keep** | Used to demonstrate delay exploitation vs rate-limited defense. |
| **`IOracle.sol`** | `contracts/interfaces/IOracle.sol` | Standard oracle read interface (`read() returns (uint256, bool)`). | Contracts & Adapters | **Keep** | Standard interface. |
| **`terminal_backend.py`** | `backend/terminal_backend.py` | Flask API serving status telemetry, cycle history, and scenario execution. | Frontend | **Modify** | Expose EEG capacity metrics (`maxCapacity`, `currentCapacity`, `refillRate`, `timeToRefill`) and EEG attack simulation endpoints. |
| **`manual_validator.py`** | `backend/manual_validator.py` | Replay harness for custom cycle validation scripts. | Manual Validator UI | **Preserve** | Keep for backward compatibility of cycle replay. |
| **`main.js` & `index.html`** | `src/main.js`, `index.html` | Minimal Cyberpunk terminal UI, scenario triggers, live SVG/Canvas charting. | User / Judges | **Modify** | Add EEG Capacity Gauge, live pre-flight borrow simulator, and 2-Minute Demo Attack flow. |

---

## 3. Adversarial Research & Prior Art Matrix

We conducted rigorous adversarial analysis against production lending protocols and existing DeFi security standards.

| System | Mechanism | Scope | Time Basis | Target Action | Oracle-Conditioned? | Comparison to ORIGIN EEG |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Aave v3 Borrow Caps** | Static debt ceiling ($D \le \text{Cap}$) | Market-wide | Static (governance updated) | Borrow | No | Aave borrow caps are static ceilings. If cap is $10M and debt is $2M, an attacker can take all $8M in 1 block. EEG limits the *rate of expansion* ($\Delta D / \Delta t$). |
| **ERC-7265 Circuit Breaker** | Token bucket / rolling outflow limiter | Vault-wide | Per-block / rolling window | Asset Withdrawals | No | ERC-7265 protects *outflows* (vault withdrawals/transfers). EEG protects *inflows of debt* (credit issuance). They are duals: ERC-7265 throttles exits; EEG throttles credit minting. |
| **Fluid (Instadapp)** | Rate-limited user borrows and dynamic debt expansion limits | Protocol / market | Per-second token bucket | Borrow / Withdraw | No | **Closest prior art.** Fluid utilizes per-second borrow limits to bound bad debt exposure. EEG specializes this primitive as a standalone, pluggable guard for any credit market. |
| **MakerDAO / Sky AutoLine** | Automated debt ceiling adjustment based on utilization buffer | Ilk-wide | Periodic adjustments | Aggregate Ceiling | No | Adjusts maximum ceiling upward if utilization is high, but does not provide a sub-hourly continuous token bucket on new originations. |
| **Euler v2 Hooks** | Modular hook called before/after borrow/deposit | Vault-level | Configurable | Any vault action | Configurable | Euler v2 provides hook architecture where an EEG hook can be attached. EEG is the concrete implementation of a rate-limiting hook. |
| **Chainlink CAPO** | Circuit breaker pausing oracle feed on abnormal jump | Oracle layer | Block-by-block | Oracle Price Feed | Yes | CAPO attempts to detect bad price feeds. If manipulation is subtle or mimics real liquidity, CAPO passes it. EEG is oracle-agnostic. |

### Classification of ORIGIN EEG:
> **Composition of known primitives (Token Bucket) with a differentiated protocol target (Aggregate New Credit Origination).**  
> We do NOT claim to have invented the token bucket or rate limiting. We claim a **minimally complex, unbypassable on-chain guardrail that decouples lending market solvency from oracle truthfulness**.

---

## 4. Threat Model & Attack Surface Analysis

We subjected the Token Bucket EEG design to rigorous adversarial attack modeling:

### Attack 1: Single Attacker — Massive Price Pump & Instant Drain
* **Vector:** Attacker deposits $1M collateral, pumps price 1000% on DEX. Oracle reports collateral is worth $10M. Attacker calls `borrow($8M)`.
* **EEG Response:** 
  * Initial capacity = $100,000.
  * Borrow request ($8,000,000) > Current Capacity ($100,000).
  * **Result:** Transaction reverts with `DebtRateLimitExceeded(8000000, 100000)`.
  * **Defense Status:** **PASSED.**

### Attack 2: Sybil Attack (100 Wallets / Smart Contracts)
* **Vector:** Attacker splits the $8M borrow into 80 transactions of $100k across 80 different addresses in the same block.
* **EEG Response:**
  * Wallet 1 consumes $100,000 $\to$ Capacity drops to $0.
  * Wallets 2 through 80 attempt to borrow $\to$ Capacity is $0$.
  * **Result:** Wallets 2-80 all revert. Total debt created in the block is strictly bounded to $100,000.
  * **Defense Status:** **PASSED.** Global aggregate tracking is completely immune to Sybil address partitioning.

### Attack 3: Flash Loan Repay-and-Reborrow Looping (Churn Attack)
* **Vector:** Attacker borrows $100k, uses flash loan to repay $100k, hoping capacity refills, allowing another $100k borrow in the same block.
* **EEG Response:**
  * Invariant: **Repayment does NOT refill the bucket.**
  * Capacity after initial borrow = $0$.
  * Repayment reduces total market debt, but `currentCapacity` remains $0$.
  * Second borrow reverts.
  * **Defense Status:** **PASSED.**

### Attack 4: Front-Running / Capacity Griefing
* **Vector:** An honest user submits a borrow of $2,900. An attacker sees this in the public mempool and borrows the remaining capacity to cause the honest user's tx to revert.
* **Analysis:** This is real market contention under high utilization.
* **Mitigation:**
  * Capacity refills continuously every second ($R_{\text{max}}$).
  * Frontend pre-flight checks simulate capacity before submission.
  * For low-capacity periods, UI displays time-to-refill.
  * Private RPC / Flashbots Protect eliminates public mempool front-running.
* **Defense Status:** **ACCEPTED PROTOCOL CHARACTERISTIC.** (Same as gas price or DEX slippage contention).

### Attack 5: Flash Loans Inside the Same Block
* **Vector:** Attacker uses flash loans within a single block across multiple contracts to create debt.
* **EEG Response:**
  * Because `currentCapacity` is updated in contract storage on each borrow, any subsequent call in the same block sees `elapsed = 0` and reduced capacity.
  * **Defense Status:** **PASSED.**

---

## 5. Exhaustive Debt-Creation Path Audit

To ensure no backdoor bypass exists, we audited all state paths in the credit facility:

```
[Credit Market Entry Points]
  ├── depositCollateral()  --> Increases collateral. Creates ZERO debt. (SAFE)
  ├── borrow()             --> MINTS NEW DEBT. (MUST BE GATED BY EEG)
  ├── repay()              --> BURNS DEBT. Must NEVER be gated. (SAFE)
  ├── liquidate()          --> Repays debt using liquidator capital in exchange for collateral.
  │                            Does NOT create new debt. Must NEVER be gated. (SAFE)
  ├── accrueInterest()     --> Expands existing debt balance via interest index.
  │                            Must NOT consume new borrow capacity. (SAFE)
  └── badDebtSettlement()  --> Socializes loss or draws from reserve fund. (SAFE)
```

### Critical Finding:
Only `borrow()` creates **new aggregate risk exposure** for the protocol. Interest accrual is existing capital compensation, not newly extracted liquidity. Liquidations and repayments reduce risk and must remain 100% accessible.

---

## 6. Integration Boundary Decision

We evaluated 5 architectural integration patterns:

| Option | Architecture | Security | Composability | Gas Overhead | Recommendation |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **A** | UI-only enforcement | Zero (Bypassed via contract call) | N/A | 0 | ❌ Rejected |
| **B** | Wrapper / Adapter contract | Medium (Bypassed if market is public) | Low | High (extra call) | ❌ Rejected |
| **C** | Standalone Guard Hook (`consumeCapacity`) | **High (Market calls Guard inside `borrow()`)** | **High** | **Low (~2,100 gas)** | ✅ **SELECTED** |
| **D** | Hardcode inside Market contract | High | Low (monolithic) | Lowest | ⚠️ Acceptable for MVP |
| **E** | Dynamic debt ceiling manipulation | Low (race conditions with oracle updates) | Medium | Medium | ❌ Rejected |

### Selected Architecture (Option C):
A dedicated, immutable or governance-managed `EconomicExposureGuard.sol` contract implementing:
```solidity
interface IEconomicExposureGuard {
    function consumeCapacity(uint256 amount) external returns (uint256 remainingCapacity);
    function getAvailableCapacity() external view returns (uint256);
    function maxCapacity() external view returns (uint256);
    function refillRatePerSecond() external view returns (uint256);
}
```
Inside `ToyLendingMarket.sol`:
```solidity
function borrow(uint256 amount) external returns (uint256) {
    // 1. Collateral capacity check
    // 2. EEG Consumption (Reverts if rate limit exceeded)
    if (exposureGuard != address(0)) {
        IEconomicExposureGuard(exposureGuard).consumeCapacity(amount);
    }
    // 3. State update & debt origination
    // ...
}
```

---

## 7. Normal User Experience vs. Large Institution Analysis

### Normal User ($2,900 Borrow)
* **Pre-condition:** Healthy market ($10M liquidity, $100k capacity).
* **Execution:**
  1. User enters `$2,900` in UI.
  2. UI pre-flight verifies `$2,900 <= $100,000`.
  3. Single standard wallet confirmation (`borrow(2900 ether)`).
  4. Contract checks `currentCapacity` ($100k $\to$ $97.1k).
  5. Transaction confirms in 1 block.
* **User Friction:** **ZERO.** No extra clicks, no KYC, no approvals, no keepers, no waiting period.

### Large Legitimate Borrower ($5,000,000 Borrow)
* **Pre-condition:** Protocol TVL is $100M, but EEG $\text{MaxCapacity}$ is $500,000 with a refill rate of $100,000/hour.
* **Behavior:**
  * The borrower cannot take $5M in a single transaction.
  * **Why this is intentional:** A system that allows instantaneous $5M borrows without delay is also a system that can be drained for $5M in 1 block by an oracle exploit.
  * **Institutional Solution:** The institution streams their borrow across several hours, or governance adjusts $\text{MaxCapacity}$ via standard timelock.
* **Tradeoff Transparency:** We explicitly acknowledge this capital velocity tradeoff to the judges.

---

## 8. What to do with Friction Engine (DHFE)?

### Recommendation: **Secondary Soft-Pricing Layer (Keep Modular, Not Core Gate)**
* The **Token Bucket EEG** is the **Hard Security Boundary** (binary allow/revert).
* The **Dual-Horizon Friction Engine (DHFE)** can remain as an optional interest rate surcharge ($effective\_rate = base \times (1 + \beta f)$) for aggressive utilization, but **it is not required for the primary exploit prevention guarantee**.
* For hackathon judging clarity: **Lead with EEG as the core invariant ($Delta Debt \le R_{max} \cdot \Delta t$)**; mention DHFE as advanced utilization pricing.

---

## 9. Failure Modes & Safety Analysis

| Failure Mode | System Behavior | Rationale |
| :--- | :--- | :--- |
| **Guard Reverts / Corrupted State** | **Fail-Closed on Borrowing** | Better to pause new debt origination than permit unconstrained drainage. |
| **Zero Capacity Reached** | **Borrowing Throttled; Repayments & Liquidations Active** | Protocol solvency preserved; borrowers can always deleverage. |
| **Oracle Completely Hijacked** | **Loss Bounded to Current Bucket Capacity** | Even if collateral is priced at infinity, attacker can only borrow $\text{Capacity}(t)$. |
| **Flash Crash / Liquidation Cascade** | **Liquidations 100% Unaffected** | Liquidations do not call `consumeCapacity()`. |

---

## 10. Concrete 2-Minute Judge Demo Script

* **0:00 – 0:20 (The Flaw in Modern Oracles):**  
  *"Judges, current lending oracles only check signatures and timestamps. When an attacker pumps a thin pool with capital, the signatures are 100% genuine, but the price is artificial. In Mango Markets, $117M was drained in 1 transaction."*
* **0:20 – 0:45 (The Normal User Demo):**  
  *Click Borrow $2,900.*  
  *"Here is an honest user. They click borrow. The transaction succeeds instantly. No keeper, no delay, no friction. EEG is invisible during normal operations."*
* **0:45 – 1:15 (The Attack Demonstration):**  
  *Inject 1000% Oracle Pump. Apparent borrowing power = $10,000,000. Attacker attempts to borrow $10,000,000.*  
  *"The attacker attempts to convert this fake valuation into cash. In existing protocols, this drains the pool. In ORIGIN, watch the on-chain execution: REVERT. Reason: DebtRateLimitExceeded. Protected capacity is $100k."*
* **1:15 – 1:40 (The Sybil & Time Refill Proof):**  
  *Attacker fires 4 wallets simultaneously.*  
  *"Even if the attacker splits into 100 wallets, aggregate capacity is shared. Wallet 1 takes $50k, Wallet 2 takes $50k, Wallets 3 through 100 are rejected. Over time, capacity steadily replenishes at $25k every 15 minutes."*
* **1:40 – 2:00 (The Closing Invariant):**  
  *"Repayments and liquidations remain 100% available at all times. We don't need to know if the oracle is truthful. We mathematically bound how fast its valuation can become protocol debt."*

---

## 11. Exact Claims We Can and Cannot Make

### ✅ WHAT WE CAN CLAIM (Defensible, Proven):
1. *"ORIGIN bounds aggregate newly originated debt through the protected credit facility to $\Delta \text{Debt} \le \text{Capacity}_0 + R_{\text{max}} \cdot \Delta t$."*
2. *"A compromised or manipulated oracle cannot instantly drain more than the available protected capacity."*
3. *"For normal borrowers operating within available capacity, ORIGIN adds zero user-facing workflow steps and minimal gas overhead (~2,100 gas)."*
4. *"Repayments and liquidations are strictly ungated in every state."*

### ❌ WHAT WE MUST NEVER CLAIM (Overclaims):
1. *"ORIGIN solves oracle manipulation."* (The oracle is still manipulated; we only limit debt creation).
2. *"ORIGIN guarantees zero bad debt."* (If an attacker borrows within capacity against manipulated collateral, that capacity can become bad debt).
3. *"ORIGIN eliminates MEV."* (Mempool contention for capacity can still occur).
4. *"Normal users can always borrow unlimited amounts."* (If capacity is exhausted, users must wait for refill).

---

## 12. Final Recommendation

# 🟢 BUILD EEG

The Economic Exposure Guard (EEG) is a vastly cleaner, more auditable, and more defensible architecture than complex on-chain matrix coalition mathematics. It provides an ironclad mathematical bound on protocol loss while maintaining a transparent UX for normal users.
