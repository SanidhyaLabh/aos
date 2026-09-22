"""
Sentinel State Controller
Monitors risk signals and synchronizes bounded state transitions with SentinelRegistry.
"""

import logging
from typing import Optional, Dict, Any
from web3 import Web3
from backend.risk.engine import RiskScoreSnapshot

logger = logging.getLogger("origin.sentinel")

STATE_MAP = {
    "NORMAL": 0,
    "DEGRADED": 1,
    "WATCH": 1,
    "STALE": 2,
    "DISPUTED": 3,
    "GUARDED": 4,
    "PROTECTIVE": 4,
    "BLOCKED": 5
}

class SentinelController:
    def __init__(self, sentinel_contract: Optional[Any] = None, tx_manager: Optional[Any] = None):
        self.contract = sentinel_contract
        self.tx_manager = tx_manager
        self.current_state = "NORMAL"

    def update_from_risk_snapshot(self, snapshot: RiskScoreSnapshot) -> str:
        """Determines if a state change should be recommended and submitted."""
        target_state = snapshot.recommended_state

        if target_state != self.current_state:
            logger.warning(
                f"Sentinel Transition: {self.current_state} -> {target_state} (Reason: {snapshot.rationale})"
            )
            self.current_state = target_state

            # If contract is connected and sender is authorized risk engine
            if self.contract and self.tx_manager:
                try:
                    target_enum = STATE_MAP.get(target_state, 0)
                    fn = self.contract.functions.updateRiskSignal(target_enum, snapshot.rationale)
                    res = self.tx_manager.send_transaction(fn)
                    logger.info(f"On-chain Sentinel state update submitted: {res.get('tx_hash')}")
                except Exception as e:
                    logger.error(f"Failed to submit on-chain Sentinel transition: {e}")

        return self.current_state
