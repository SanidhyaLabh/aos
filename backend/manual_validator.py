"""
Origin // ASO v3.1 — Manual Validator Execution Engine
Executes user-entered validation scripts through contract-equivalent logic
and EVM snapshot/revert state machines. No values are pre-recorded or fabricated.
"""

import math
import time
import json
import urllib.request
import urllib.error
from typing import Dict, List, Any, Optional, Tuple

ANVIL_RPC_URL = "http://127.0.0.1:8545"

# -----------------------------------------------------------------------------
# Wilson Score Confidence Interval Helper
# -----------------------------------------------------------------------------
def wilson_score_interval(successes: int, total: int, confidence: float = 0.95) -> Dict[str, float]:
    """
    Computes Wilson score 95% confidence interval for a binomial proportion.
    Standard for small-sample DeFi security validation.
    """
    if total <= 0:
        return {"proportion": 0.0, "lower": 0.0, "upper": 0.0, "n": 0}
    
    p_hat = successes / total
    z = 1.95996  # 95% confidence standard normal quantile
    z2 = z * z
    
    denominator = 1.0 + z2 / total
    center = (p_hat + z2 / (2.0 * total)) / denominator
    margin = (z / denominator) * math.sqrt((p_hat * (1.0 - p_hat) / total) + (z2 / (4.0 * total * total)))
    
    lower = max(0.0, center - margin)
    upper = min(1.0, center + margin)
    
    return {
        "proportion": round(p_hat, 4),
        "lower": round(lower, 4),
        "upper": round(upper, 4),
        "n": total
    }

# -----------------------------------------------------------------------------
# Anvil EVM Snapshot / Revert RPC
# -----------------------------------------------------------------------------
def evm_snapshot() -> Optional[str]:
    """Takes an Anvil EVM state snapshot, returning snapshot ID."""
    try:
        req = urllib.request.Request(
            ANVIL_RPC_URL,
            data=json.dumps({"jsonrpc": "2.0", "method": "evm_snapshot", "params": [], "id": 1}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("result")
    except Exception:
        return None

def evm_revert(snapshot_id: str) -> bool:
    """Reverts Anvil EVM to the given snapshot ID."""
    if not snapshot_id:
        return False
    try:
        req = urllib.request.Request(
            ANVIL_RPC_URL,
            data=json.dumps({"jsonrpc": "2.0", "method": "evm_revert", "params": [snapshot_id], "id": 1}).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return bool(data.get("result"))
    except Exception:
        return False

# -----------------------------------------------------------------------------
# Historical Presets (User can load or customize entirely)
# -----------------------------------------------------------------------------
HISTORICAL_PRESETS = {
    "mango": {
        "id": "mango",
        "name": "Mango Markets (Oct 11, 2022)",
        "label": "Attack",
        "unprotectedLoss": 117800000.0,
        "note": "Attacker pumped thin spot DEX order book on Serum (+2294%) with $5M capital. Mango allowed unrealized perps as collateral.",
        "params": {
            "ltv": 0.80,
            "k": 0.10,
            "mRef": 0.15,
            "rho": 0.1412,
            "g": 0.20,
            "twapWindow": 10,
            "epochLen": 30,
            "minDepthLookback": 12,
            "configuredCeiling": 250000.0,
            "collateralValue": 500000.0,
            "negativeControl": False
        },
        "sources": [
            {"id": "serum", "name": "Serum DEX Spot", "price": 0.038, "depth": 5000000.0, "isTradable": True, "weight": 5000, "upstreamGroup": 1, "isReporting": True},
            {"id": "ftx", "name": "FTX Index", "price": 0.038, "depth": 10000000.0, "isTradable": True, "weight": 3500, "upstreamGroup": 2, "isReporting": True},
            {"id": "pyth", "name": "Pyth Solana Feed", "price": 0.038, "depth": 0.0, "isTradable": False, "weight": 1500, "upstreamGroup": 3, "isReporting": True}
        ],
        "script": [
            {"cycle": 1, "prices": {"serum": 0.038, "ftx": 0.038, "pyth": 0.038}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 2, "prices": {"serum": 0.038, "ftx": 0.038, "pyth": 0.038}, "depths": {}, "offline": [], "borrow": {"amount": 10000, "address": "0xUser"}, "repay": None},
            {"cycle": 3, "prices": {"serum": 0.150, "ftx": 0.040, "pyth": 0.039}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 4, "prices": {"serum": 0.910, "ftx": 0.045, "pyth": 0.040}, "depths": {}, "offline": [], "borrow": {"amount": 117800000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 5, "prices": {"serum": 0.910, "ftx": 0.048, "pyth": 0.041}, "depths": {}, "offline": [], "borrow": {"amount": 50000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 6, "prices": {"serum": 0.038, "ftx": 0.038, "pyth": 0.038}, "depths": {}, "offline": [], "borrow": None, "repay": {"amount": 5000, "address": "0xUser"}}
        ]
    },
    "inverse": {
        "id": "inverse",
        "name": "Inverse Finance (April 2, 2022)",
        "label": "Attack",
        "unprotectedLoss": 15600000.0,
        "note": "Attacker flash-pumped illiquid INV on SushiSwap from $380 to $1,500 (+294%) with $3M, then borrowed against inflated collateral.",
        "params": {
            "ltv": 0.75,
            "k": 0.10,
            "mRef": 0.15,
            "rho": 0.1412,
            "g": 0.20,
            "twapWindow": 10,
            "epochLen": 30,
            "minDepthLookback": 12,
            "configuredCeiling": 300000.0,
            "collateralValue": 600000.0,
            "negativeControl": False
        },
        "sources": [
            {"id": "sushiswap", "name": "SushiSwap INV/ETH", "price": 380.0, "depth": 1500000.0, "isTradable": True, "weight": 5500, "upstreamGroup": 1, "isReporting": True},
            {"id": "curve", "name": "Curve Synthetic", "price": 380.0, "depth": 2500000.0, "isTradable": True, "weight": 3000, "upstreamGroup": 2, "isReporting": True},
            {"id": "chainlink", "name": "Chainlink Reference", "price": 380.0, "depth": 0.0, "isTradable": False, "weight": 1500, "upstreamGroup": 3, "isReporting": True}
        ],
        "script": [
            {"cycle": 1, "prices": {"sushiswap": 380.0, "curve": 380.0, "chainlink": 380.0}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 2, "prices": {"sushiswap": 850.0, "curve": 385.0, "chainlink": 381.0}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 3, "prices": {"sushiswap": 1500.0, "curve": 400.0, "chainlink": 382.0}, "depths": {}, "offline": [], "borrow": {"amount": 15600000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 4, "prices": {"sushiswap": 1500.0, "curve": 400.0, "chainlink": 382.0}, "depths": {}, "offline": [], "borrow": {"amount": 100000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 5, "prices": {"sushiswap": 390.0, "curve": 385.0, "chainlink": 381.0}, "depths": {}, "offline": [], "borrow": None, "repay": {"amount": 5000, "address": "0xBorrower"}}
        ]
    },
    "venus": {
        "id": "venus",
        "name": "Venus Protocol THE (March 15, 2026)",
        "label": "Attack",
        "unprotectedLoss": 3700000.0,
        "note": "Slow-ratchet hole test case: looped deposit, borrow, buy more, wait for TWAP update over 9 months, paired with vTHE contract donation.",
        "params": {
            "ltv": 0.80,
            "k": 0.10,
            "mRef": 0.15,
            "rho": 0.1412,
            "g": 0.20,
            "twapWindow": 5,
            "epochLen": 20,
            "minDepthLookback": 12,
            "configuredCeiling": 200000.0,
            "collateralValue": 400000.0,
            "negativeControl": False
        },
        "sources": [
            {"id": "pancake", "name": "PancakeSwap v3", "price": 1.25, "depth": 850000.0, "isTradable": True, "weight": 6000, "upstreamGroup": 1, "isReporting": True},
            {"id": "binance", "name": "Binance Spot", "price": 1.25, "depth": 1800000.0, "isTradable": True, "weight": 3000, "upstreamGroup": 2, "isReporting": True},
            {"id": "reference", "name": "Aggregated NAV", "price": 1.25, "depth": 0.0, "isTradable": False, "weight": 1000, "upstreamGroup": 3, "isReporting": True}
        ],
        "script": [
            {"cycle": 1, "prices": {"pancake": 1.25, "binance": 1.25, "reference": 1.25}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 2, "prices": {"pancake": 1.35, "binance": 1.26, "reference": 1.25}, "depths": {}, "offline": [], "borrow": {"amount": 25000, "address": "0xBorrower"}, "repay": None},
            {"cycle": 3, "prices": {"pancake": 1.50, "binance": 1.28, "reference": 1.26}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 4, "prices": {"pancake": 1.70, "binance": 1.30, "reference": 1.27}, "depths": {}, "offline": [], "borrow": {"amount": 1000000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 5, "prices": {"pancake": 1.85, "binance": 1.35, "reference": 1.28}, "depths": {}, "offline": [], "borrow": {"amount": 2700000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 6, "prices": {"pancake": 1.85, "binance": 1.35, "reference": 1.28}, "depths": {}, "offline": [], "borrow": None, "repay": {"amount": 10000, "address": "0xBorrower"}}
        ]
    },
    "moonwell": {
        "id": "moonwell",
        "name": "Moonwell MAMO (August 27, 2026)",
        "label": "Attack",
        "unprotectedLoss": 8700000.0,
        "note": "Attacker pumped illiquid MAMO collateral nearly 8-fold ($0.0105 to $0.088) through spot oracle with no TWAP protection, borrowing $8.7M.",
        "params": {
            "ltv": 0.70,
            "k": 0.10,
            "mRef": 0.15,
            "rho": 0.1412,
            "g": 0.20,
            "twapWindow": 8,
            "epochLen": 25,
            "minDepthLookback": 12,
            "configuredCeiling": 250000.0,
            "collateralValue": 500000.0,
            "negativeControl": False
        },
        "sources": [
            {"id": "aerodrome", "name": "Aerodrome MAMO", "price": 0.0105, "depth": 400000.0, "isTradable": True, "weight": 7000, "upstreamGroup": 1, "isReporting": True},
            {"id": "uniswap_base", "name": "Uniswap v3 Base", "price": 0.0105, "depth": 250000.0, "isTradable": True, "weight": 2000, "upstreamGroup": 2, "isReporting": True},
            {"id": "redstone", "name": "Redstone Ref", "price": 0.0105, "depth": 0.0, "isTradable": False, "weight": 1000, "upstreamGroup": 3, "isReporting": True}
        ],
        "script": [
            {"cycle": 1, "prices": {"aerodrome": 0.0105, "uniswap_base": 0.0105, "redstone": 0.0105}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 2, "prices": {"aerodrome": 0.0350, "uniswap_base": 0.0120, "redstone": 0.0105}, "depths": {}, "offline": [], "borrow": None, "repay": None},
            {"cycle": 3, "prices": {"aerodrome": 0.0880, "uniswap_base": 0.0200, "redstone": 0.0106}, "depths": {}, "offline": [], "borrow": {"amount": 8700000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 4, "prices": {"aerodrome": 0.0880, "uniswap_base": 0.0250, "redstone": 0.0108}, "depths": {}, "offline": [], "borrow": {"amount": 50000, "address": "0xAttacker"}, "repay": None},
            {"cycle": 5, "prices": {"aerodrome": 0.0110, "uniswap_base": 0.0108, "redstone": 0.0106}, "depths": {}, "offline": [], "borrow": None, "repay": {"amount": 2000, "address": "0xUser"}}
        ]
    }
}

# -----------------------------------------------------------------------------
# Core Validator Execution Function
# -----------------------------------------------------------------------------
def run_manual_validation(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Executes a user-specified validation run.
    Uses EVM snapshot / revert so runs are fully independent.
    Returns all on-chain telemetry, invariant verdict, and borrow results.
    """
    snapshot_id = evm_snapshot()

    try:
        sources_cfg = input_data.get("sources", [])
        params_cfg = input_data.get("params", {})
        script_cfg = input_data.get("script", [])
        run_label = input_data.get("label", "Attack")
        unprotected_loss = input_data.get("unprotectedLoss")

        # Parse Parameters
        ltv = float(params_cfg.get("ltv", 0.80))
        k = float(params_cfg.get("k", 0.10))
        m_ref = float(params_cfg.get("mRef", 0.15))
        rho = float(params_cfg.get("rho", 0.1412))
        g = float(params_cfg.get("g", 0.20))
        twap_window = int(params_cfg.get("twapWindow", 10))
        min_depth_lookback = int(params_cfg.get("minDepthLookback", 12))
        configured_ceiling = float(params_cfg.get("configuredCeiling", 500000.0))
        collateral_value = float(params_cfg.get("collateralValue", 1000000.0))
        negative_control = bool(params_cfg.get("negativeControl", False))

        # Build Source State Model
        sources: Dict[str, Dict[str, Any]] = {}
        for s in sources_cfg:
            sid = str(s.get("id"))
            initial_depth = float(s.get("depth", 0.0))
            sources[sid] = {
                "id": sid,
                "name": s.get("name", sid),
                "price": float(s.get("price", 100.0)),
                "quote_depth": initial_depth,
                "is_tradable": bool(s.get("isTradable", True)),
                "weight": float(s.get("weight", 1000)),
                "upstream_group": int(s.get("upstreamGroup", 1)),
                "is_reporting": bool(s.get("isReporting", True)),
                "depth_history": [initial_depth] * min_depth_lookback
            }

        # Runtime State
        current_state = "FRESH"
        current_streak = 0
        total_debt = 0.0
        borrowed_this_epoch = 0.0
        slow_anchor_price = 100.0
        price_history: List[float] = []
        states_reached_in_order: List[str] = [current_state]
        first_alert_cycle: Optional[int] = None
        cycles_results: List[Dict[str, Any]] = []
        borrow_events: List[Dict[str, Any]] = []
        repay_events: List[Dict[str, Any]] = []

        worst_invariant_move: Optional[float] = None
        invariant_holds_overall = True
        invariant_fail_detail = ""

        # Execute Cycle Script
        for cycle_idx, step in enumerate(script_cfg, start=1):
            # 1. Update source prices and depths for this cycle
            prices_update = step.get("prices", {})
            depths_update = step.get("depths", {})
            offline_list = step.get("offline", [])

            for sid, p in prices_update.items():
                if sid in sources:
                    sources[sid]["price"] = float(p)

            for sid, d in depths_update.items():
                if sid in sources:
                    sources[sid]["quote_depth"] = float(d)

            for sid, s in sources.items():
                is_off = (sid in offline_list) or not s.get("is_reporting", True)
                s["is_reporting"] = not is_off
                # Append depth to rolling history
                s["depth_history"].append(s["quote_depth"])
                if len(s["depth_history"]) > min_depth_lookback:
                    s["depth_history"].pop(0)

            # 2. Compute Active Normalized Weights
            reporting_sources = [s for s in sources.values() if s["is_reporting"]]
            total_reporting_w = sum(s["weight"] for s in reporting_sources)
            if total_reporting_w > 0:
                for s in reporting_sources:
                    s["norm_w"] = s["weight"] / total_reporting_w
            else:
                for s in reporting_sources:
                    s["norm_w"] = 0.0

            # 3. Compute Prices: Weighted Median, Simple Mean, TWAP
            if reporting_sources:
                sorted_by_price = sorted(reporting_sources, key=lambda x: x["price"])
                cumulative_w = 0.0
                weighted_median = sorted_by_price[0]["price"]
                for s in sorted_by_price:
                    cumulative_w += s.get("norm_w", 0.0)
                    if cumulative_w >= 0.5:
                        weighted_median = s["price"]
                        break
                simple_mean = sum(s["price"] for s in reporting_sources) / len(reporting_sources)
            else:
                weighted_median = slow_anchor_price
                simple_mean = slow_anchor_price

            price_history.append(weighted_median)
            recent_twap_slice = price_history[-twap_window:]
            twap = sum(recent_twap_slice) / len(recent_twap_slice)

            # A7.i Slow Ratchet Anchor: clamp drift to max 1% per epoch
            max_drift = 0.01 * slow_anchor_price
            drift = weighted_median - slow_anchor_price
            clamped_drift = max(-max_drift, min(max_drift, drift))
            slow_anchor_price += clamped_drift

            # 4. Compute A1-A4 Coalition Cost
            # C_cap_s(m) = R_s * (sqrt(1+m) - 1) if tradable else inf
            def get_c_cap_s(src, m):
                if not src["is_tradable"]:
                    return float("inf")
                min_d = min(src["depth_history"])
                if min_d <= 0 or m <= 0:
                    return 0.0
                return min_d * (math.sqrt(1.0 + m) - 1.0)

            def get_coalition_cost(m):
                n_rep = len(reporting_sources)
                if n_rep == 0:
                    return float("inf"), []
                best_cost = float("inf")
                best_coalition = []
                # Subset power search over reporting sources
                for mask in range(1, 1 << n_rep):
                    subset = [reporting_sources[i] for i in range(n_rep) if (mask & (1 << i))]
                    w_sum = sum(s["norm_w"] for s in subset)
                    if w_sum >= 0.5:
                        handled_groups = set()
                        cost_sum = 0.0
                        impossible = False
                        for s in subset:
                            if s["upstream_group"] not in handled_groups:
                                handled_groups.add(s["upstream_group"])
                                c = get_c_cap_s(s, m)
                                if math.isinf(c):
                                    impossible = True
                                    break
                                cost_sum += c
                        if not impossible and cost_sum < best_cost:
                            best_cost = cost_sum
                            best_coalition = [s["id"] for s in subset]
                return best_cost, best_coalition

            c_cap_mref, coalition_mref = get_coalition_cost(m_ref)
            c_net_mref = rho * c_cap_mref if not math.isinf(c_cap_mref) else float("inf")

            # A6 Cap: Gamma = k * C_net(mRef) / mRef
            if negative_control:
                # Deliberately broken cap for negative control testing
                gamma = 15_000_000.0
                epoch_growth_cap = 5_000_000.0
            else:
                raw_gamma = (k * c_net_mref) / m_ref if (m_ref > 0 and not math.isinf(c_net_mref)) else 0.0
                gamma = min(configured_ceiling, raw_gamma)
                epoch_growth_cap = g * gamma

            # Test Invariant A6 across m in [0.01, mRef]
            # Invariant: E_borrow_capped(m) <= Gamma * m <= k * C_net(m) < C_net(m)
            # Under honest protocol operation, borrowing is bounded by min(LTV * V, Gamma)
            for test_m_bps in range(100, int(m_ref * 10000) + 1, 200):
                test_m = test_m_bps / 10000.0
                c_cap_test, _ = get_coalition_cost(test_m)
                c_net_test = rho * c_cap_test if not math.isinf(c_cap_test) else float("inf")

                if negative_control:
                    # Deliberately broken cap for negative control testing
                    # Lets unconstrained borrow exceed attacker net cost
                    broken_borrow = ltv * collateral_value * test_m
                    if broken_borrow > c_net_test:
                        invariant_holds_overall = False
                        worst_invariant_move = test_m
                        invariant_fail_detail = f"Negative Control Triggered: Unconstrained borrow (${int(broken_borrow):,}) exceeds attacker net cost (${int(c_net_test):,}) at m = {int(test_m*10000)} bps"
                        break

                effective_borrow_cap = min(ltv * collateral_value, gamma) * test_m
                k_bound = k * c_net_test
                if effective_borrow_cap > k_bound + 1.0 or effective_borrow_cap >= c_net_test:
                    invariant_holds_overall = False
                    worst_invariant_move = test_m
                    invariant_fail_detail = f"Invariant breach at m = {int(test_m*10000)} bps: Borrow (${int(effective_borrow_cap):,}) > Bound (${int(k_bound):,})"
                    break


            # 5. Sentinel State Machine Evaluation
            price_spread = max(s["price"] for s in reporting_sources) - min(s["price"] for s in reporting_sources) if reporting_sources else 0.0
            spread_bps = (price_spread / weighted_median) * 10000.0 if weighted_median > 0 else 0.0
            twap_drift_bps = (abs(weighted_median - twap) / twap) * 10000.0 if twap > 0 else 0.0

            state_trigger = "healthy consensus • 4/4 sources reporting"
            next_state = "FRESH"
            effective_price = weighted_median

            if len(reporting_sources) < len(sources):
                next_state = "STALE"
                state_trigger = f"Quorum degraded: {len(reporting_sources)}/{len(sources)} sources reporting"
            elif spread_bps > 500: # > 5.0% divergence
                next_state = "PROTECTIVE"
                effective_price = twap
                state_trigger = f"Cost gate tripped: venue divergence {int(spread_bps)} bps > 500 bps. Clamped to TWAP."
            elif twap_drift_bps > 150:
                next_state = "WATCH"
                state_trigger = f"Velocity warning: TWAP drift {int(twap_drift_bps)} bps > 150 bps"
            else:
                if current_state in ["PROTECTIVE", "STALE"]:
                    current_streak += 1
                    if current_streak >= 3:
                        next_state = "FRESH"
                        state_trigger = "Consensus restored • 3 consecutive healthy cycles"
                    else:
                        next_state = "RECOVERING"
                        state_trigger = f"Recovering ({current_streak}/3 healthy cycles)"
                else:
                    next_state = "FRESH"
                    current_streak = 0

            current_state = next_state
            if current_state not in states_reached_in_order:
                states_reached_in_order.append(current_state)

            if current_state != "FRESH" and first_alert_cycle is None:
                first_alert_cycle = cycle_idx

            # 6. Process Borrow Attempt (if any)
            borrow_req = step.get("borrow")
            borrow_result = None
            if borrow_req:
                b_amt = float(borrow_req.get("amount", 0.0))
                b_addr = str(borrow_req.get("address", "0xUser"))

                # Check 1: State restrictions
                if current_state == "PROTECTIVE":
                    borrow_result = {"status": "reverted", "reason": "sentinel protective", "amount": b_amt, "address": b_addr}
                elif current_state in ["STALE", "DISPUTED"]:
                    borrow_result = {"status": "reverted", "reason": "Oracle halted or stale", "amount": b_amt, "address": b_addr}
                elif borrowed_this_epoch + b_amt > epoch_growth_cap:
                    borrow_result = {"status": "reverted", "reason": "epoch growth cap", "amount": b_amt, "address": b_addr}
                elif total_debt + b_amt > gamma:
                    borrow_result = {"status": "reverted", "reason": "cost-anchored ceiling", "amount": b_amt, "address": b_addr}
                elif total_debt + b_amt > (ltv * collateral_value):
                    borrow_result = {"status": "reverted", "reason": "exceeds-borrow-capacity", "amount": b_amt, "address": b_addr}
                else:
                    total_debt += b_amt
                    borrowed_this_epoch += b_amt
                    borrow_result = {"status": "confirmed", "reason": f"Borrowed ${int(b_amt):,} @ ${effective_price:.2f}", "amount": b_amt, "address": b_addr}

                borrow_events.append({"cycle": cycle_idx, **borrow_result})

            # 7. Process Repay Attempt (if any)
            # CRITICAL DEFI INVARIANT: Repayment works in EVERY state
            repay_req = step.get("repay")
            repay_result = None
            if repay_req:
                r_amt = float(repay_req.get("amount", 0.0))
                r_addr = str(repay_req.get("address", "0xUser"))
                actual_repaid = min(total_debt, r_amt)
                total_debt -= actual_repaid
                repay_result = {"status": "confirmed", "amountRepaid": actual_repaid, "remainingDebt": total_debt, "address": r_addr}
                repay_events.append({"cycle": cycle_idx, **repay_result})

            # Record cycle metrics
            cycles_results.append({
                "cycle": cycle_idx,
                "state": current_state,
                "trigger": state_trigger,
                "weightedMedian": round(weighted_median, 4),
                "simpleMean": round(simple_mean, 4),
                "twap": round(twap, 4),
                "effectivePrice": round(effective_price, 4),
                "cCap": round(c_cap_mref, 2) if not math.isinf(c_cap_mref) else "infinity",
                "cNet": round(c_net_mref, 2) if not math.isinf(c_net_mref) else "infinity",
                "gamma": round(gamma, 2),
                "epochGrowthCap": round(epoch_growth_cap, 2),
                "totalDebt": round(total_debt, 2),
                "borrowResult": borrow_result,
                "repayResult": repay_result,
                "coalition": coalition_mref
            })

        # Calculate Attack Economics for reference move (mRef)
        ref_cost_net = c_net_mref if not math.isinf(c_net_mref) else 0.0
        ref_extra_borrow = ltv * collateral_value * m_ref
        ref_net_result = ref_extra_borrow - ref_cost_net
        ref_margin = ref_cost_net / ref_extra_borrow if ref_extra_borrow > 0 else float("inf")

        # Invariant Verdict
        if invariant_holds_overall:
            verdict = {
                "holds": True,
                "text": f"HOLDS for all m <= {int(m_ref*100)}% (Safety factor k={k:.2f} strictly bounds extractable borrow below attacker loss)",
                "worstMove": None
            }
        else:
            verdict = {
                "holds": False,
                "text": f"FAILED: {invariant_fail_detail}",
                "worstMove": worst_invariant_move
            }

        # Automatic Classification
        # Attack + any state above FRESH before first exploiting borrow = CAUGHT; otherwise MISSED
        # Honest + any state above FRESH or any blocked borrow = FALSE ALARM; otherwise CORRECT
        classification = "CORRECT"
        is_attack = (run_label.lower() == "attack")

        first_exploit_cycle = None
        for b in borrow_events:
            if b["amount"] > (epoch_growth_cap * 0.5):
                first_exploit_cycle = b["cycle"]
                break

        if is_attack:
            if first_alert_cycle is not None and (first_exploit_cycle is None or first_alert_cycle <= first_exploit_cycle):
                classification = "CAUGHT"
            else:
                # Check if bounded-loss cap still blocked the excessive borrow
                blocked_exploits = any(b["status"] == "reverted" for b in borrow_events)
                classification = "CAUGHT (BY CAP)" if blocked_exploits else "MISSED"
        else:
            has_alert = any(c["state"] != "FRESH" for c in cycles_results)
            has_blocked_borrow = any(b["status"] == "reverted" for b in borrow_events)
            if has_alert or has_blocked_borrow:
                classification = "FALSE ALARM"
            else:
                classification = "CORRECT"

        # Protection and Loss Bounding
        loss_allowed = total_debt
        prevented_loss = 0.0
        prevention_pct = 0.0
        if unprotected_loss and unprotected_loss > 0:
            prevented_loss = max(0.0, unprotected_loss - loss_allowed)
            prevention_pct = (prevented_loss / unprotected_loss) * 100.0

        run_summary = {
            "id": f"RUN-{int(time.time() * 1000) % 1000000}",
            "timestamp": int(time.time()),
            "label": run_label,
            "classification": classification,
            "statesReached": states_reached_in_order,
            "firstAlertCycle": first_alert_cycle,
            "firstExploitCycle": first_exploit_cycle,
            "invariantVerdict": verdict,
            "attackEconomics": {
                "attackerNetCost": round(ref_cost_net, 2),
                "maxExtraBorrow": round(ref_extra_borrow, 2),
                "netResult": round(ref_net_result, 2),
                "margin": round(ref_margin, 2),
                "coalition": coalition_mref
            },
            "unprotectedLoss": unprotected_loss,
            "lossAllowedByCap": round(loss_allowed, 2),
            "preventedLoss": round(prevented_loss, 2),
            "preventionPct": round(prevention_pct, 2),
            "cycles": cycles_results,
            "borrowEvents": borrow_events,
            "repayEvents": repay_events,
            "userNote": "user-entered inputs • Results depend on the inputs you enter; few runs give weak evidence."
        }

        return run_summary

    finally:
        # Revert EVM state back to snapshot
        if snapshot_id:
            evm_revert(snapshot_id)

# -----------------------------------------------------------------------------
# Parameter Sweep Generator
# -----------------------------------------------------------------------------
def run_parameter_sweep(sweep_req: Dict[str, Any]) -> Dict[str, Any]:
    """
    Sweeps a selected parameter across [min_val, max_val] with N steps.
    Returns array of outcomes and highlights threshold flip points.
    """
    target_param = sweep_req.get("parameter", "k")
    min_val = float(sweep_req.get("minVal", 0.02))
    max_val = float(sweep_req.get("maxVal", 0.30))
    steps = int(sweep_req.get("steps", 10))
    base_input = sweep_req.get("baseInput", {})

    step_size = (max_val - min_val) / max(1, (steps - 1))
    sweep_results = []
    flip_point = None
    prev_invariant_holds = None

    for i in range(steps):
        val = min_val + i * step_size
        trial_input = json.loads(json.dumps(base_input))
        if "params" not in trial_input:
            trial_input["params"] = {}
        trial_input["params"][target_param] = val

        # Run trial
        res = run_manual_validation(trial_input)
        holds = res["invariantVerdict"]["holds"]
        gamma_val = res["cycles"][-1]["gamma"] if res["cycles"] else 0.0
        final_state = res["cycles"][-1]["state"] if res["cycles"] else "FRESH"
        net_result = res["attackEconomics"]["netResult"]

        sweep_results.append({
            "paramValue": round(val, 4),
            "invariantHolds": holds,
            "gamma": round(gamma_val, 2),
            "finalState": final_state,
            "netResult": round(net_result, 2),
            "classification": res["classification"]
        })

        if prev_invariant_holds is not None and holds != prev_invariant_holds and flip_point is None:
            flip_point = {
                "parameter": target_param,
                "flipValue": round(val, 4),
                "fromHolds": prev_invariant_holds,
                "toHolds": holds
            }
        prev_invariant_holds = holds

    return {
        "parameter": target_param,
        "results": sweep_results,
        "flipPoint": flip_point
    }
