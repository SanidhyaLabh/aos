"""
DHFE Calibration Script
Backtests the Dual-Horizon Friction Engine's convex friction function and
EWMA decay against real historical price data + known manipulation incidents.

This does NOT train a black-box model. It grid-searches the existing,
explainable convex formula's parameters (steepness k_phi, decay lambda)
to find values that:
  (a) keep friction near-zero during real calm/normal trading periods, and
  (b) spike friction during known historical manipulation incident windows.

Usage:
    pip install requests pandas numpy
    python calibrate_dhfe.py

Extend INCIDENTS below with entries from your own incidents.csv.
"""

import requests
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# ---------------------------------------------------------------------------
# 1. Historical incidents — extend this from your existing incidents.csv
#    Each entry: (name, asset_id_on_coingecko, incident_start, incident_end)
#    Windows should be tight around the actual manipulation, not the whole day.
# ---------------------------------------------------------------------------
INCIDENTS = [
    # Example structure — replace with real, verified timestamps from your
    # own incidents.csv before relying on this for anything real.
    # ("mango-markets-oct-2022", "mango-markets", "2022-10-11T00:00:00", "2022-10-11T12:00:00"),
]

# ---------------------------------------------------------------------------
# 2. Fetch historical hourly price data (CoinGecko free public API, no key)
# ---------------------------------------------------------------------------
def fetch_price_history(coin_id: str, days: int = 90) -> pd.DataFrame:
    url = f"https://api.coingecko.com/api/v3/coins/{coin_id}/market_chart"
    params = {"vs_currency": "usd", "days": days, "interval": "hourly"}
    resp = requests.get(url, params=params, timeout=30)
    resp.raise_for_status()
    data = resp.json()["prices"]  # list of [timestamp_ms, price]
    df = pd.DataFrame(data, columns=["ts_ms", "price"])
    df["ts"] = pd.to_datetime(df["ts_ms"], unit="ms")
    df = df.drop(columns=["ts_ms"]).set_index("ts")
    return df


# ---------------------------------------------------------------------------
# 3. Simulate the friction engine over a price series for given parameters
# ---------------------------------------------------------------------------
def convex_phi(u: float, k_phi: float) -> float:
    """Convex friction function: near-zero for small u, steep as u -> 1."""
    u = max(0.0, min(u, 1.0))
    return u ** k_phi  # k_phi > 1 => more convex / steeper near the top


def simulate_friction(
    df: pd.DataFrame,
    gamma_headroom: float,
    lam: float,
    k_phi: float,
    borrow_fraction_of_move: float = 5.0,
) -> pd.Series:
    """
    Approximates per-hour 'implied borrow size' from realized price moves
    (as a stand-in for real borrow tx data you don't have historically),
    then runs it through the instantaneous + cumulative friction signals.

    In a real backtest, replace `implied_x` with actual historical borrow
    transaction sizes from The Graph / Dune once you have them per protocol.
    """
    returns = df["price"].pct_change().abs().fillna(0)
    implied_x = returns * gamma_headroom * borrow_fraction_of_move

    ewma_exposure = 0.0
    friction_series = []
    for x in implied_x:
        f_inst = convex_phi(x / gamma_headroom, k_phi)
        ewma_exposure = lam * ewma_exposure + (1 - lam) * x
        f_cum = convex_phi(ewma_exposure / gamma_headroom, k_phi)
        f_final = f_inst + f_cum - f_inst * f_cum
        friction_series.append(f_final)

    return pd.Series(friction_series, index=df.index)


# ---------------------------------------------------------------------------
# 4. Score a parameter set: low friction on calm days, high on incident windows
# ---------------------------------------------------------------------------
def score_params(friction: pd.Series, incident_windows: list) -> dict:
    is_incident = pd.Series(False, index=friction.index)
    for start, end in incident_windows:
        is_incident |= (friction.index >= start) & (friction.index <= end)

    calm_friction = friction[~is_incident]
    incident_friction = friction[is_incident] if is_incident.any() else pd.Series([np.nan])

    return {
        "calm_mean_friction": calm_friction.mean(),
        "calm_p95_friction": calm_friction.quantile(0.95),  # false-positive risk
        "incident_mean_friction": incident_friction.mean(),
        "separation": incident_friction.mean() - calm_friction.mean(),
    }


# ---------------------------------------------------------------------------
# 5. Grid search over lambda / k_phi
# ---------------------------------------------------------------------------
def calibrate(coin_id: str, incident_windows: list, gamma_headroom: float = 1.0):
    print(f"Fetching {coin_id} history...")
    df = fetch_price_history(coin_id)

    lambdas = [0.90, 0.93, 0.95, 0.97, 0.99]
    k_phis = [2, 3, 4, 6]

    results = []
    for lam in lambdas:
        for k_phi in k_phis:
            friction = simulate_friction(df, gamma_headroom, lam, k_phi)
            scores = score_params(friction, incident_windows)
            scores.update({"lambda": lam, "k_phi": k_phi})
            results.append(scores)

    results_df = pd.DataFrame(results).sort_values(
        by=["calm_p95_friction", "separation"], ascending=[True, False]
    )
    print("\nTop candidate parameter sets (low calm-day friction, high separation):")
    print(results_df.head(10).to_string(index=False))
    return results_df


if __name__ == "__main__":
    # Example: calibrate against a volatile asset with no labeled incidents yet.
    # Add real incident windows to INCIDENTS (converted to (start, end) tuples
    # of pandas Timestamps) once you've pulled verified dates from your own
    # incidents.csv and rekt.news / DeFiLlama hack records.
    incident_windows = [
        (pd.Timestamp(start), pd.Timestamp(end))
        for _, _, start, end in INCIDENTS
    ]
    calibrate("ethereum", incident_windows)
