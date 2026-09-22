"""
Exposure Monitor Module
Tracks real-time capacity and utilization across Global, Risk-Group, and Market EEG buckets.
"""

from typing import Dict, Any, Optional
from web3 import Web3

class ExposureMonitor:
    def __init__(self, w3: Web3, contracts_map: Dict[str, Any]):
        self.w3 = w3
        self.contracts = contracts_map

    def get_bucket_telemetry(self, bucket_contract: Any, tier_name: str, display_name: str) -> Dict[str, Any]:
        """Queries on-chain token-bucket state."""
        if not bucket_contract:
            return {
                "tier": tier_name,
                "name": display_name,
                "available": 0.0,
                "max": 0.0,
                "total_issued": 0.0,
                "utilization_pct": 0.0
            }

        try:
            avail_wad = bucket_contract.functions.getAvailableCapacity().call()
            max_wad = bucket_contract.functions.maxCapacity().call()
            total_wad = 0
            if hasattr(bucket_contract.functions, "totalIssued"):
                total_wad = bucket_contract.functions.totalIssued().call()

            avail = float(Web3.from_wei(avail_wad, "ether"))
            max_cap = float(Web3.from_wei(max_wad, "ether"))
            total_issued = float(Web3.from_wei(total_wad, "ether"))
            util_pct = (1.0 - (avail / max_cap)) * 100.0 if max_cap > 0 else 0.0

            return {
                "tier": tier_name,
                "name": display_name,
                "address": bucket_contract.address,
                "available": round(avail, 2),
                "max": round(max_cap, 2),
                "total_issued": round(total_issued, 2),
                "utilization_pct": round(max(0.0, min(100.0, util_pct)), 2)
            }
        except Exception:
            return {
                "tier": tier_name,
                "name": display_name,
                "available": 0.0,
                "max": 0.0,
                "total_issued": 0.0,
                "utilization_pct": 0.0
            }

    def get_full_hierarchical_exposure(self) -> Dict[str, Any]:
        """Returns consolidated snapshot of all three EEG tiers."""
        global_telemetry = self.get_bucket_telemetry(
            self.contracts.get("GlobalExposureGuard"),
            "GLOBAL",
            "Global Protocol Guard"
        )
        rwa_group_telemetry = self.get_bucket_telemetry(
            self.contracts.get("RiskGroupExposureGuard"),
            "RISK_GROUP",
            "RWA Risk Group Guard"
        )
        market_telemetry = self.get_bucket_telemetry(
            self.contracts.get("EconomicExposureGuard"),
            "MARKET",
            "RWAUSD Market Guard"
        )

        return {
            "global": global_telemetry,
            "risk_groups": {
                "RWA": rwa_group_telemetry
            },
            "markets": {
                "RWAUSD": market_telemetry
            }
        }
