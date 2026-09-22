"""
Price Source Abstract Interface and Normalized Observation Dataclass
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Dict, Any

@dataclass
class PriceObservation:
    asset_id: str
    source_id: str
    source_group: str
    price: float
    timestamp: int
    received_at: datetime = field(default_factory=datetime.utcnow)
    decimals: int = 18
    quote_currency: str = "USD"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_wad(self) -> int:
        """Converts floating price to 18-decimal integer Wad."""
        return int(self.price * 10**18)

class PriceSource(ABC):
    def __init__(self, source_id: str, source_group: str, provider: str, data_domain: str):
        self.source_id = source_id
        self.source_group = source_group
        self.provider = provider
        self.data_domain = data_domain
        self.is_active = True

    @abstractmethod
    async def get_price(self, asset: str) -> Optional[PriceObservation]:
        """Fetches and normalizes live valuation for the requested asset."""
        pass
