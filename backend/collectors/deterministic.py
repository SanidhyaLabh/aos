"""
Deterministic / Staging Price Source Adapter
Provides predictable, reproducible price observations for testing, calibration, and local runs.
"""

import time
from typing import Optional
from backend.collectors.base import PriceSource, PriceObservation

class DeterministicPriceSource(PriceSource):
    def __init__(
        self,
        source_id: str,
        source_group: str,
        provider: str,
        data_domain: str,
        base_price: float = 100.0,
        nominal_offset: float = 0.0,
        latency_ms: int = 25
    ):
        super().__init__(source_id, source_group, provider, data_domain)
        self.base_price = base_price
        self.nominal_offset = nominal_offset
        self.latency_ms = latency_ms
        self.override_price: Optional[float] = None
        self.is_offline = False

    async def get_price(self, asset: str) -> Optional[PriceObservation]:
        if not self.is_active or self.is_offline:
            return None

        if self.override_price is not None:
            effective_price = self.override_price
        else:
            effective_price = self.base_price + self.nominal_offset

        now_ts = int(time.time())

        return PriceObservation(
            asset_id=asset,
            source_id=self.source_id,
            source_group=self.source_group,
            price=round(effective_price, 4),
            timestamp=now_ts,
            decimals=18,
            quote_currency="USD",
            metadata={
                "provider": self.provider,
                "data_domain": self.data_domain,
                "latency_ms": self.latency_ms
            }
        )
