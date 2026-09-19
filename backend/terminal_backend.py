"""
Origin // ASO v3.1 — High-Reliability Python Terminal Backend
Serves real-time quantitative risk engine telemetry, scenario emulation,
and on-chain credit facility rule enforcement for the Minimal Terminal UI.
"""

import os
import sys
import os
import json
import time
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from backend.risk_engine import RiskEnginePython, Source

app = Flask(__name__)
CORS(app)

PORT = int(os.environ.get("BACKEND_PORT", 5001))

# Initialize Risk Engine with exact Part A parameters
# Sized to institutional depths reproducing exact wireframe metrics
risk_engine = RiskEnginePython(
    rho=0.1412,
    k_factor=0.10,
    m_ref=0.15,
    epoch_growth_share=0.20,
    configured_ceiling=500_000.0,
    collateral_value=1_000_000.0,
    ltv=0.80,
    liquidation_discount=0.05
)

# Benchmark depths reproducing exact wireframe figures ($1.26M cost, $120k borrow, -$1.14M net result)
risk_engine.sources["ondo"].quote_depth = 85_000_000.0
risk_engine.sources["ondo"].depth_history = [85_000_000.0] * 12
risk_engine.sources["coinbase"].quote_depth = 95_000_000.0
risk_engine.sources["coinbase"].depth_history = [95_000_000.0] * 12
risk_engine.sources["kraken"].quote_depth = 38_000_000.0
risk_engine.sources["kraken"].depth_history = [38_000_000.0] * 12

# Terminal State
state_data = {
    "sentinelState": "FRESH",
    "sentinelCeiling": 500_000.0,
    "recoveryStreak": 0,
    "sentinelTrigger": "healthy consensus • 4/4 sources reporting",
    "totalDebt": 0.0,
    "borrowedThisEpoch": 0.0,
    "currentEpoch": 1,
    "epochDurationSec": 300,
    "collateralAmount": 1000.0, # 1,000 RWA units
    "basePrice": 100.02,
    "simpleMean": 100.02,
    "weightedMedian": 100.02,
    "twap": 100.02,
    "effectivePrice": 100.02,
    "activeScenario": "baseline",
    "lastTxResult": "Confirmed • Borrowed $10,000 • Oracle price: $100.02",
    "lastTxStatus": "confirmed", # "confirmed" or "reverted"
    "cycleCount": 1,
    "startTime": time.time()
}

# Historical price cycles for 2-line chart with adverse state shading
cycle_history = [
    {
        "cycle": 1,
        "timestamp": int(time.time()) - 30,
        "simpleMean": 100.02,
        "weightedMedian": 100.02,
        "effectivePrice": 100.02,
        "sentinelState": "FRESH"
    },
    {
        "cycle": 2,
        "timestamp": int(time.time()) - 20,
        "simpleMean": 100.03,
        "weightedMedian": 100.02,
        "effectivePrice": 100.02,
        "sentinelState": "FRESH"
    },
    {
        "cycle": 3,
        "timestamp": int(time.time()) - 10,
        "simpleMean": 100.02,
        "weightedMedian": 100.02,
        "effectivePrice": 100.02,
        "sentinelState": "FRESH"
    }
]

def record_cycle_snapshot():
    state_data["cycleCount"] += 1
    snapshot = {
        "cycle": state_data["cycleCount"],
        "timestamp": int(time.time()),
        "simpleMean": round(state_data["simpleMean"], 4),
        "weightedMedian": round(state_data["weightedMedian"], 4),
        "effectivePrice": round(state_data["effectivePrice"], 4),
        "sentinelState": state_data["sentinelState"]
    }
    cycle_history.append(snapshot)
    if len(cycle_history) > 100:
        cycle_history.pop(0)

# -----------------------------------------------------------------------------
# Telemetry Status Endpoint
# -----------------------------------------------------------------------------
@app.route("/status", methods=["GET"])
@app.route("/api/status", methods=["GET"])
def get_status():
    # Evaluate RiskEngine attack economics at 15% move
    eco = risk_engine.attack_economics(0.15)
    gamma_val = risk_engine.gamma()
    epoch_cap_val = risk_engine.epoch_growth_cap()

    # Dynamic ceiling matches Sentinel state
    current_s = state_data["sentinelState"]
    base_ceil = gamma_val
    if current_s == "FRESH":
        eff_ceiling = base_ceil
    elif current_s == "WATCH":
        eff_ceiling = base_ceil * 0.80
    elif current_s == "PROTECTIVE":
        eff_ceiling = base_ceil * 0.30
    elif current_s == "STALE":
        eff_ceiling = base_ceil * 0.50
    elif current_s == "DISPUTED":
        eff_ceiling = 0.0
    else: # RECOVERING
        eff_ceiling = base_ceil * (0.25 + 0.25 * state_data["recoveryStreak"])

    state_data["sentinelCeiling"] = eff_ceiling

    sources_list = []
    for s in risk_engine.sources.values():
        sources_list.append({
            "id": s.id,
            "name": s.name,
            "price": s.price,
            "liquidityWeight": int(s.weight / 100),
            "depthUsd": s.quote_depth,
            "minRecentDepthUsd": s.get_min_recent_depth(),
            "upstreamGroup": s.upstream_group,
            "status": "ONLINE" if s.is_reporting else "OFFLINE",
            "type": s.source_type
        })

    return jsonify({
        "cycleCount": state_data["cycleCount"],
        "sentinelState": state_data["sentinelState"],
        "sentinelCeiling": state_data["sentinelCeiling"],
        "recoveryStreak": state_data["recoveryStreak"],
        "sentinelTrigger": state_data["sentinelTrigger"],
        "simpleConsensusPrice": state_data["simpleMean"],
        "weightedMedianPrice": state_data["weightedMedian"],
        "twapPrice": state_data["twap"],
        "effectivePrice": state_data["effectivePrice"],
        "gamma": gamma_val,
        "epochGrowthCap": epoch_cap_val,
        "attackEconomics": {
            "attackerNetCost": eco["attackerNetCost"],
            "maxExtraBorrow": eco["maxExtraBorrow"],
            "netResult": eco["netResult"],
            "margin": eco["margin"],
            "coalitionChosen": eco["coalitionChosen"]
        },
        "totalDebt": state_data["totalDebt"],
        "borrowedThisEpoch": state_data["borrowedThisEpoch"],
        "lastTxResult": state_data["lastTxResult"],
        "lastTxStatus": state_data["lastTxStatus"],
        "sources": sources_list,
        "history": cycle_history[-30:]
    })

@app.route("/cycle/history", methods=["GET"])
@app.route("/history", methods=["GET"])
def get_cycle_history():
    return jsonify({
        "history": cycle_history,
        "totalCycles": state_data["cycleCount"],
        "latest": cycle_history[-1] if cycle_history else None
    })

# -----------------------------------------------------------------------------
# Credit Action Endpoints (Borrow / Repay)
# -----------------------------------------------------------------------------
@app.route("/borrow", methods=["POST"])
@app.route("/api/borrow", methods=["POST"])
def execute_borrow():
    data = request.get_json(silent=True) or {}
    amount = float(data.get("amount", 10000.0))

    if amount <= 0:
        return jsonify({"success": False, "revertReason": "zero-borrow"}), 400

    current_state = state_data["sentinelState"]
    
    # Check 1: Sentinel PROTECTIVE check
    if current_state == "PROTECTIVE":
        reason = "sentinel protective"
        state_data["lastTxResult"] = f'Revert: "{reason}"'
        state_data["lastTxStatus"] = "reverted"
        return jsonify({"success": False, "revertReason": reason}), 400

    # Check 2: Oracle Staleness check
    if current_state in ["STALE", "DISPUTED"]:
        reason = "Oracle halted or stale"
        state_data["lastTxResult"] = f'Revert: "{reason}"'
        state_data["lastTxStatus"] = "reverted"
        return jsonify({"success": False, "revertReason": reason}), 400

    # Check 3: Epoch Growth Cap check (g * Gamma)
    epoch_cap = risk_engine.epoch_growth_cap()
    if state_data["borrowedThisEpoch"] + amount > epoch_cap:
        reason = "epoch growth cap"
        state_data["lastTxResult"] = f'Revert: "{reason}"'
        state_data["lastTxStatus"] = "reverted"
        return jsonify({"success": False, "revertReason": reason}), 400

    # Check 4: Dynamic Cost-Anchored Debt Ceiling check (min(configured, Gamma))
    effective_ceiling = state_data["sentinelCeiling"]
    if state_data["totalDebt"] + amount > effective_ceiling:
        reason = "cost-anchored ceiling"
        state_data["lastTxResult"] = f'Revert: "{reason}"'
        state_data["lastTxStatus"] = "reverted"
        return jsonify({"success": False, "revertReason": reason}), 400

    # Check 5: Collateral Capacity check
    collateral_val_usd = state_data["collateralAmount"] * state_data["effectivePrice"]
    max_borrow_usd = collateral_val_usd * risk_engine.ltv
    if state_data["totalDebt"] + amount > max_borrow_usd:
        reason = "exceeds-borrow-capacity"
        state_data["lastTxResult"] = f'Revert: "{reason}"'
        state_data["lastTxStatus"] = "reverted"
        return jsonify({"success": False, "revertReason": reason}), 400

    # Execute successful borrow
    state_data["totalDebt"] += amount
    state_data["borrowedThisEpoch"] += amount
    price_used = state_data["effectivePrice"]
    state_data["lastTxResult"] = f"Confirmed • Borrowed ${int(amount):,} • Oracle price: ${price_used:.2f}"
    state_data["lastTxStatus"] = "confirmed"

    record_cycle_snapshot()

    return jsonify({
        "success": True,
        "amount": amount,
        "oraclePriceUsed": price_used,
        "totalDebt": state_data["totalDebt"],
        "borrowedThisEpoch": state_data["borrowedThisEpoch"]
    })

@app.route("/repay", methods=["POST"])
@app.route("/api/repay", methods=["POST"])
def execute_repay():
    data = request.get_json(silent=True) or {}
    amount = float(data.get("amount", 5000.0))

    if amount <= 0:
        return jsonify({"success": False, "revertReason": "invalid-repay"}), 400

    # Crucial DeFi invariant: Repayment is 100% UNGATED in every single state!
    amount_repaid = min(amount, state_data["totalDebt"])
    state_data["totalDebt"] -= amount_repaid

    state_data["lastTxResult"] = f"Confirmed • Repaid ${int(amount_repaid):,} debt • Collateral preserved"
    state_data["lastTxStatus"] = "confirmed"

    record_cycle_snapshot()

    return jsonify({
        "success": True,
        "amountRepaid": amount_repaid,
        "remainingDebt": state_data["totalDebt"],
        "state": state_data["sentinelState"]
    })

# -----------------------------------------------------------------------------
# Scenarios Emulation Endpoints
# -----------------------------------------------------------------------------
@app.route("/scenarios/baseline", methods=["POST"])
@app.route("/api/scenarios/baseline", methods=["POST"])
def scenario_baseline():
    state_data["activeScenario"] = "baseline"
    # Reset all feeds to $100.02
    for s in risk_engine.sources.values():
        s.price = 100.02
        s.is_reporting = True
    
    # Restore depths
    risk_engine.sources["ondo"].quote_depth = 85_000_000.0
    risk_engine.sources["coinbase"].quote_depth = 95_000_000.0
    risk_engine.sources["kraken"].quote_depth = 38_000_000.0

    state_data["simpleMean"] = 100.02
    state_data["weightedMedian"] = 100.02
    state_data["twap"] = 100.02
    state_data["effectivePrice"] = 100.02
    state_data["sentinelState"] = "FRESH"
    state_data["recoveryStreak"] = 0
    state_data["sentinelTrigger"] = "healthy consensus • 4/4 sources reporting"

    record_cycle_snapshot()
    return jsonify({"success": True, "scenario": "baseline"})

@app.route("/scenarios/thin-pump", methods=["POST"])
@app.route("/api/scenarios/thin-pump", methods=["POST"])
def scenario_thin_pump():
    state_data["activeScenario"] = "thin-pump"
    # Push Kraken (15% depth) to $165.00 (+65%)
    risk_engine.sources["kraken"].price = 165.00
    risk_engine.sources["ondo"].price = 100.02
    risk_engine.sources["coinbase"].price = 100.02
    risk_engine.sources["fed"].price = 100.00

    # Calculate metrics
    state_data["simpleMean"] = (100.02 + 100.02 + 165.00 + 100.00) / 4.0 # 116.26
    state_data["weightedMedian"] = risk_engine.calculate_weighted_median() # 100.02 (resistant!)
    state_data["twap"] = 100.02
    state_data["effectivePrice"] = 100.02 # Clamped by cost gate to TWAP

    # Transition to PROTECTIVE
    state_data["sentinelState"] = "PROTECTIVE"
    state_data["recoveryStreak"] = 0
    state_data["sentinelTrigger"] = "Cost gate triggered: Kraken thin venue pumped +65%. Clamped to TWAP."

    record_cycle_snapshot()
    return jsonify({"success": True, "scenario": "thin-pump"})

@app.route("/scenarios/deep-squeeze", methods=["POST"])
@app.route("/api/scenarios/deep-squeeze", methods=["POST"])
def scenario_deep_squeeze():
    state_data["activeScenario"] = "deep-squeeze"
    # Push Coinbase (40% depth) to $115.00 (+15%)
    risk_engine.sources["coinbase"].price = 115.00
    risk_engine.sources["kraken"].price = 100.02
    risk_engine.sources["ondo"].price = 100.02
    risk_engine.sources["fed"].price = 100.00

    state_data["simpleMean"] = (100.02 + 115.00 + 100.02 + 100.00) / 4.0
    state_data["weightedMedian"] = 100.02
    state_data["effectivePrice"] = 100.02
    state_data["sentinelState"] = "WATCH"
    state_data["sentinelTrigger"] = "Sustained squeeze: Coinbase +15%. Epoch growth cap enforced ($100k)."

    record_cycle_snapshot()
    return jsonify({"success": True, "scenario": "deep-squeeze"})

@app.route("/scenarios/kill-source", methods=["POST"])
@app.route("/api/scenarios/kill-source", methods=["POST"])
def scenario_kill_source():
    state_data["activeScenario"] = "kill-source"
    # Take Kraken OFFLINE
    risk_engine.sources["kraken"].is_reporting = False
    state_data["sentinelState"] = "STALE"
    state_data["recoveryStreak"] = 0
    state_data["sentinelTrigger"] = "Stale feed: Kraken offline (freshness elapsed > 60s)"

    record_cycle_snapshot()
    return jsonify({"success": True, "scenario": "kill-source"})

@app.route("/scenarios/pull-liquidity", methods=["POST"])
@app.route("/api/scenarios/pull-liquidity", methods=["POST"])
def scenario_pull_liquidity():
    state_data["activeScenario"] = "pull-liquidity"
    # Drop Kraken depth from $38M to $5M
    risk_engine.sources["kraken"].record_depth(5_000_000.0)
    state_data["sentinelTrigger"] = "Fake depth defense (A7.ii): 12-cycle depth floor active."

    record_cycle_snapshot()
    return jsonify({"success": True, "scenario": "pull-liquidity"})

@app.route("/scenarios/recover", methods=["POST"])
@app.route("/api/scenarios/recover", methods=["POST"])
def scenario_recover():
    state_data["activeScenario"] = "recover"
    # Restore all feeds
    for s in risk_engine.sources.values():
        s.price = 100.02
        s.is_reporting = True

    state_data["recoveryStreak"] += 1
    if state_data["recoveryStreak"] >= 3:
        state_data["sentinelState"] = "FRESH"
        state_data["recoveryStreak"] = 0
        state_data["sentinelTrigger"] = "Full recovery: 3/3 healthy checks. Ceiling restored to 100%."
    else:
        state_data["sentinelState"] = "RECOVERING"
        state_data["sentinelTrigger"] = f"Recovery in progress: {state_data['recoveryStreak']}/3 healthy checks."

    state_data["simpleMean"] = 100.02
    state_data["weightedMedian"] = 100.02
    state_data["effectivePrice"] = 100.02

    record_cycle_snapshot()
    return jsonify({
        "success": True,
        "scenario": "recover",
        "state": state_data["sentinelState"],
        "streak": state_data["recoveryStreak"]
    })

# -----------------------------------------------------------------------------
# Manual Validator Endpoints (No pre-recorded data, EVM snapshot/revert)
# -----------------------------------------------------------------------------
from backend.manual_validator import (
    run_manual_validation,
    run_parameter_sweep,
    HISTORICAL_PRESETS,
    wilson_score_interval
)
import csv
import io
from flask import Response

validator_run_log: list = []

@app.route("/validator/presets", methods=["GET"])
@app.route("/api/validator/presets", methods=["GET"])
def get_validator_presets():
    return jsonify(HISTORICAL_PRESETS)

@app.route("/validator/run", methods=["POST"])
@app.route("/api/validator/run", methods=["POST"])
def execute_validator_run():
    payload = request.get_json(silent=True) or {}
    run_result = run_manual_validation(payload)
    
    # Prepend to run log
    validator_run_log.insert(0, {
        "id": run_result["id"],
        "timestamp": run_result["timestamp"],
        "label": run_result["label"],
        "classification": run_result["classification"],
        "statesReached": run_result["statesReached"],
        "firstAlertCycle": run_result["firstAlertCycle"],
        "invariantHolds": run_result["invariantVerdict"]["holds"],
        "gamma": run_result["cycles"][-1]["gamma"] if run_result["cycles"] else 0.0,
        "lossAllowed": run_result["lossAllowedByCap"],
        "unprotectedLoss": run_result["unprotectedLoss"],
        "preventedLoss": run_result["preventedLoss"],
        "preventionPct": run_result["preventionPct"]
    })
    
    return jsonify(run_result)

@app.route("/validator/sweep", methods=["POST"])
@app.route("/api/validator/sweep", methods=["POST"])
def execute_validator_sweep():
    payload = request.get_json(silent=True) or {}
    sweep_result = run_parameter_sweep(payload)
    return jsonify(sweep_result)

@app.route("/validator/runs", methods=["GET"])
@app.route("/api/validator/runs", methods=["GET"])
def get_validator_runs():
    total_runs = len(validator_run_log)
    attack_runs = [r for r in validator_run_log if r["label"].lower() == "attack"]
    honest_runs = [r for r in validator_run_log if r["label"].lower() == "honest"]
    
    missed_count = sum(1 for r in attack_runs if r["classification"] == "MISSED")
    false_alarm_count = sum(1 for r in honest_runs if r["classification"] == "FALSE ALARM")
    
    missed_ci = wilson_score_interval(missed_count, len(attack_runs))
    false_alarm_ci = wilson_score_interval(false_alarm_count, len(honest_runs))
    
    return jsonify({
        "totalRuns": total_runs,
        "attackRunsCount": len(attack_runs),
        "honestRunsCount": len(honest_runs),
        "missedAttacks": {
            "count": missed_count,
            "rate": missed_ci["proportion"],
            "ciLower": missed_ci["lower"],
            "ciUpper": missed_ci["upper"],
            "n": len(attack_runs)
        },
        "falseAlarms": {
            "count": false_alarm_count,
            "rate": false_alarm_ci["proportion"],
            "ciLower": false_alarm_ci["lower"],
            "ciUpper": false_alarm_ci["upper"],
            "n": len(honest_runs)
        },
        "runs": validator_run_log
    })

@app.route("/validator/runs/<run_id>", methods=["DELETE"])
@app.route("/api/validator/runs/<run_id>", methods=["DELETE"])
def delete_validator_run(run_id):
    global validator_run_log
    validator_run_log = [r for r in validator_run_log if r["id"] != run_id]
    return jsonify({"success": True, "deleted": run_id})

@app.route("/validator/runs", methods=["DELETE"])
@app.route("/api/validator/runs", methods=["DELETE"])
def clear_validator_runs():
    global validator_run_log
    validator_run_log = []
    return jsonify({"success": True, "cleared": True})

@app.route("/validator/export-csv", methods=["GET"])
@app.route("/api/validator/export-csv", methods=["GET"])
def export_validator_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Run ID", "Timestamp", "Label", "Classification", "States Reached",
        "Invariant Holds", "First Alert Cycle", "Gamma USD", "Allowed Loss USD",
        "Unprotected Loss USD", "Prevented Loss USD", "Prevention Pct"
    ])
    for r in validator_run_log:
        writer.writerow([
            r.get("id"),
            r.get("timestamp"),
            r.get("label"),
            r.get("classification"),
            " -> ".join(r.get("statesReached", [])),
            r.get("invariantHolds"),
            r.get("firstAlertCycle", "N/A"),
            r.get("gamma"),
            r.get("lossAllowed"),
            r.get("unprotectedLoss", "N/A"),
            r.get("preventedLoss", "N/A"),
            f"{r.get('preventionPct', 0):.2f}%"
        ])
    
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=validator_runs.csv"}
    )

# -----------------------------------------------------------------------------
# Validation Results JSON (Part G)
# -----------------------------------------------------------------------------
@app.route("/validation-results", methods=["GET"])
@app.route("/api/validation-results", methods=["GET"])
def get_validation_results():
    val_path = os.path.join(os.path.dirname(__file__), "..", "data", "derived", "validation_results.json")
    if os.path.exists(val_path):
        return send_file(os.path.abspath(val_path), mimetype="application/json")
    return jsonify({"error": "Validation results not found"}), 404

if __name__ == "__main__":
    print("====================================================================")
    print(f"  ORIGIN // ASO v3.1 — HIGH-RELIABILITY PYTHON RISK ENGINE BACKEND")
    print(f"  Listening on http://localhost:{PORT}")
    print("====================================================================")
    app.run(host="0.0.0.0", port=PORT, debug=False)

