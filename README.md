# ORIGIN — Economic Exposure Guard (EEG)

> **On-chain Economic Exposure Guard that limits how quickly a lending market can create new debt, ensuring that even a manipulated oracle cannot be converted into an unlimited instantaneous liquidity drain.**

Repository: `https://github.com/AnantSharmaDev768/aso-sentinel` (Multipli Hackathon 2026)  
Active Branch: `feat/economic-exposure-guard`

---

## 🎯 The Core Thesis

Oracle manipulation attacks (e.g. Mango Markets, Inverse Finance, Platypus, Venus) become catastrophic when a false or manipulated collateral price can **instantly unlock 100% of the remaining borrowing liquidity** in a lending market within a single transaction.

Instead of trying to prove whether an oracle is "truthful" or "honest" (an undecidable problem under deep manipulation or private mempool attacks), **ORIGIN EEG** enforces a mathematical debt-velocity invariant:

$$\Delta \text{Debt}_{\text{new}} \le \text{Capacity}_0 + R_{\text{max}} \times \Delta t$$

**Meaning:** Aggregate newly originated debt across the entire lending market cannot exceed the configured debt-expansion capacity over time.

---

## 🛡️ Key Architectural Invariants

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

## ⚡ Quick Start (Windows One-Click Launcher)

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

## ⏱️ 2-Minute Judge Demo Sequence

On the Terminal UI (`http://localhost:5173/terminal`), use the **`2-MIN DEMO`** interactive bar:

| Step | Button | Action | Invariant Demonstrated |
| :--- | :--- | :--- | :--- |
| **0:00–0:20** | **`1. Normal ($2.9k)`** | Honest user borrows $\$2,900$. | **Seamless UX**: 1 standard transaction, no delays, no extra approvals. |
| **0:20–0:45** | **`2. $10M Exploit`** | Oracle pumped $+1000\%$, attacker requests $\$10\text{M}$ drain. | **Hard Revert**: On-chain revert `ExceedsAvailableCapacity(10000000, 97100)`. Loss is bounded. |
| **0:45–1:15** | **`3. Sybil (4 Wallets)`** | 4 distinct attacker wallets try concurrent borrows ($\$50\text{k}, \$13\text{k}, \$50\text{k}, \$100\text{k}$). | **Sybil Resistance**: Wallets 1 & 2 consume remaining capacity; Wallets 3 & 4 revert on-chain. |
| **1:15–1:40** | **`4. Refill (+15m)`** | Fast-forward timestamp $+900\text{s}$ ($+15$ min). | **Continuous Refill**: Bucket replenishes linearly by $+\$25,000$. |
| **1:40–2:00** | **`5. Repay`** | User repays $\$2,900$ debt. | **DeFi Invariant**: Repay is 100% ungated and does **not** refill capacity. |

---

## 🔍 Prior Art Matrix

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

## 🧪 Test Suite & Invariants

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

## ⚖️ Claims & Non-Claims

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
