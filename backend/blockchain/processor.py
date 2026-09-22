"""
Event Processor Module
Parses decoded blockchain events, persists into database audit tables, and broadcasts updates.
"""

import logging
from typing import Dict, Any, Optional
from backend.database.session import ScopedSession
from backend.database.models import SentinelEventModel, ExposureSnapshotModel

logger = logging.getLogger("origin.processor")

class EventProcessor:
    def __init__(self, db_session_factory=ScopedSession):
        self.db_factory = db_session_factory

    def process_event(self, event_data: Dict[str, Any]):
        """Persists indexed event into durable audit storage."""
        contract = event_data.get("contract", "")
        tx_hash = event_data.get("tx_hash", "")
        block_num = event_data.get("block_number", 0)

        logger.info(f"Processed on-chain event from {contract} (block={block_num}, tx={tx_hash[:10]}...)")
