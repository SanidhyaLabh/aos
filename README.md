# Origin // ASO v3.1 — Manipulation-Cost-Aware Oracle & Bounded-Loss Architecture

**Multipli Hackathon 2026** — Verifiable Freshness, Manipulation Cost Awareness & Bounded-Loss Debt Ceilings for DeFi Lending Facilities.

Origin ASO upgrades decentralized oracle architecture from simply securing the *messenger* (cryptographic signatures, freshness proofs) to mathematically bounding protocol exposure when the *underlying market itself is pushed with capital*.

---

## ⚡ Quick Start (Windows One-Click Launcher)

Double-click or run:
```bat
run.bat
```
This automatically starts:
1. **Python Risk Engine Backend** on `http://localhost:5001`
2. **Frontend Interactive Terminal** on `http://localhost:5173/terminal`
3. Automatically launches `http://localhost:5173/terminal` in your default browser.

---

## 🛠️ Manual Startup Guide

If you prefer running services manually in separate terminals:

### 1. Start Anvil Local EVM Node
```bash
anvil --port 8545 --chain-id 31337
```

### 2. Compile & Deploy Smart Contracts
```bash
npm run compile
npm run deploy
```

### 3. Start Python Risk Engine Backend
```bash
python -m pip install flask flask-cors
python backend/terminal_backend.py
```
> *Runs on `http://localhost:5001`. Handles quantitative risk telemetry, EVM snapshot isolation, and manual validator execution.*

### 4. Start Vite Dev Server
```bash
npm install
npm run dev
```
> *Open [http://localhost:5173/terminal](http://localhost:5173/terminal) in your browser.*

---

## 🏛️ System Architecture & Defense Layers

Origin // ASO v3.1 defends downstream lending facilities across three distinct layers:

```
[Layer 1: Verifiable Freshness & Quorum]
   ├── Cryptographic EIP-191 signatures from bonded attesters
   ├── Strict freshness limits (<= 60 seconds staleness)
   └── Divergence bounds across multi-source quorum (<= 50 bps)
            │
            ▼
[Layer 2: Manipulation Cost Gate (Part A Formulations)]
   ├── Constant-Product Slippage Modeling: C_cap(m) = R * (sqrt(1+m) - 1)
   ├── Coalition Search: Attacker must push >= 50% normalized reporting weight
   ├── Empirical Net-Loss Modeling: C_net(m) = rho * C_cap(m) (rho = 0.1412)
   └── Clamping: If manipulation cost is cheap, effective price clamps to TWAP
            │
            ▼
[Layer 3: Bounded-Loss Dynamic Debt Ceilings]
   ├── Cost-Anchored Ceiling: Gamma = k * C_net(mRef) / mRef
   ├── Epoch Borrow Growth Budget: epochGrowthCap = g * Gamma
   ├── Sentinel Circuit Breaker: FRESH (100%) -> WATCH (80%) -> PROTECTIVE (30%) -> STALE (50%) -> DISPUTED (0%)
   └── Critical Invariant: repay() is ALWAYS UNGATED in every Sentinel state
```

---

## 🧪 Interactive Manual Risk Validator

Click **`[Validator ⚙]`** in the terminal scenario bar to launch the live evaluation harness:

- **100% User-Entered Inputs:** Edit spot prices, depths ($USD$), weights, tradability flags, and script actions. Nothing is pre-recorded.
- **EVM Snapshot Isolation:** Every run takes an Anvil `evm_snapshot`, executes the cycle script through the deployed contracts, and calls `evm_revert` to guarantee independent runs.
- **Preloaded Historical Presets:**
  - **Mango Markets (Oct 11, 2022):** Demonstrates cost gate tripping in Cycle 3, reverting a $117.8M exploit in Cycle 4 (100% loss prevented).
  - **Inverse Finance (Apr 2, 2022):** Flash-pump of illiquid INV pool (+294%) neutralized.
  - **Venus Protocol THE (Mar 15, 2026):** Slow-ratchet attack blocked via 24h drift clamping.
  - **Moonwell MAMO (Aug 27, 2026):** Unprotected spot pump caught by minimum recent depth defense.
- **Negative Control:** Toggle `"Deliberately wrong cap (negative control)"` to scientifically demonstrate the invariant verdict turning `FAILED`.
- **Parameter Sensitivity Sweep:** Sweeps parameters ($k, \rho, m_{\text{Ref}}, g$) and plots threshold flip points.
- **Statistical Run Log:** Records every run with automatic classification (`CAUGHT`, `MISSED`, `FALSE ALARM`, `CORRECT`) and computes **Wilson 95% Confidence Intervals**.

---

## 📜 License

Apache 2.0 / MIT — Developed for Multipli Hackathon 2026.
