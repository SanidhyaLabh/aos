"""
Quantitative Risk Engine for ORIGIN
Calculates deterministic multi-factor risk scores and debt velocity telemetry.
"""

from dataclasses import dataclass, field
from typing import Dict, Any, List
import time

@dataclass
class RiskScoreSnapshot:
    asset_id: str
    oracle_risk: float        # 0.0 (low) to 1.0 (critical)
    exposure_risk: float      # 0.0 to 1.0 based on bucket utilization
    debt_velocity_risk: float # 0.0 to 1.0 based on debt growth per hour
    attestation_risk: float   # 0.0 to 1.0 based on divergence and source count
    composite_risk_score: float
    recommended_state: str    # NORMAL, DEGRADED, GUARDED, BLOCKED
    rationale: str
    timestamp: int = field(default_factory=lambda: int(time.time()))

class ProductionRiskEngine:
    def __init__(
        self,
        normal_velocity_limit_per_hr: float = 100_000.0,
        elevated_velocity_limit_per_hr: float = 300_000.0,
        critical_velocity_limit_per_hr: float = 600_000.0
    ):
        self.normal_velocity_limit = normal_velocity_limit_per_hr
        self.elevated_velocity_limit = elevated_velocity_limit_per_hr
        self.critical_velocity_limit = critical_velocity_limit_per_hr

    def evaluate_risk(
        self,
        asset_id: str,
        oracle_freshness_seconds: float,
        source_count: int,
        divergence_bps: float,
        available_capacity: float,
        max_capacity: float,
        borrowed_in_last_hour: float,
        is_oracle_paused: bool = False
    ) -> RiskScoreSnapshot:
        # 1. Oracle Risk
        if is_oracle_paused:
            oracle_risk = 1.0
        elif oracle_freshness_seconds > 60:
            oracle_risk = 0.9
        elif oracle_freshness_seconds > 30:
            oracle_risk = 0.4
        else:
            oracle_risk = 0.05

        # 2. Attestation / Divergence Risk
        if source_count < 3:
            attestation_risk = 1.0
        elif divergence_bps > 50:
            attestation_risk = 0.9
        elif divergence_bps > 30:
            attestation_risk = 0.4
        else:
            attestation_risk = 0.05

        # 3. Exposure / Capacity Risk
        utilization = 1.0 - (available_capacity / max_capacity) if max_capacity > 0 else 1.0
        if utilization >= 0.95:
            exposure_risk = 0.9
        elif utilization >= 0.75:
            exposure_risk = 0.5
        else:
            exposure_risk = 0.1

        # 4. Debt Velocity Risk
        if borrowed_in_last_hour >= self.critical_velocity_limit:
            velocity_risk = 1.0
        elif borrowed_in_last_hour >= self.elevated_velocity_limit:
            velocity_risk = 0.6
        elif borrowed_in_last_hour >= self.normal_velocity_limit:
            velocity_risk = 0.3
        else:
            velocity_risk = 0.05

        # Weighted composite score
        composite = (
            0.35 * oracle_risk +
            0.25 * attestation_risk +
            0.20 * exposure_risk +
            0.20 * velocity_risk
        )

        # Deterministic Sentinel State recommendation
        if oracle_risk >= 0.9 or attestation_risk >= 0.9:
            recommended_state = "BLOCKED"
            rationale = "Oracle failure or unacceptable source divergence"
        elif velocity_risk >= 0.6 or composite >= 0.55:
            recommended_state = "GUARDED"
            rationale = "Abnormal debt velocity or elevated exposure risk"
        elif composite >= 0.30:
            recommended_state = "DEGRADED"
            rationale = "Minor feed degradation or moderate utilization"
        else:
            recommended_state = "NORMAL"
            rationale = "All telemetry indicators healthy"

        return RiskScoreSnapshot(
            asset_id=asset_id,
            oracle_risk=round(oracle_risk, 2),
            exposure_risk=round(exposure_risk, 2),
            debt_velocity_risk=round(velocity_risk, 2),
            attestation_risk=round(attestation_risk, 2),
            composite_risk_score=round(composite, 2),
            recommended_state=recommended_state,
            rationale=rationale
        )
