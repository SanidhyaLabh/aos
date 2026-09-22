"""
Observation Normalization and Strict Data Sanitization Engine
"""

import time
import math
from typing import Optional, List
from backend.collectors.base import PriceObservation

class NormalizationError(ValueError):
    """Raised when an external observation fails strict sanity bounds."""
    pass

class DataNormalizer:
    def __init__(self, max_allowed_future_seconds: int = 15, default_max_staleness: int = 86400):
        self.max_allowed_future_seconds = max_allowed_future_seconds
        self.default_max_staleness = default_max_staleness

    def normalize(self, obs: PriceObservation) -> PriceObservation:
        """
        Applies strict validation and formatting on raw price observation.
        Raises NormalizationError if observation is invalid.
        """
        now = int(time.time())

        # 1. Price Value Sanity Check
        if obs.price is None or math.isnan(obs.price) or math.isinf(obs.price):
            raise NormalizationError(f"Non-numeric price received from source {obs.source_id}: {obs.price}")

        if obs.price <= 0.0:
            raise NormalizationError(f"Non-positive price received from source {obs.source_id}: {obs.price}")

        # 2. Timestamp Sanity Check
        if obs.timestamp > (now + self.max_allowed_future_seconds):
            raise NormalizationError(
                f"Future timestamp rejected from source {obs.source_id}: "
                f"obs.timestamp={obs.timestamp}, now={now}, delta={obs.timestamp - now}s"
            )

        age = now - obs.timestamp
        if age > self.default_max_staleness:
            raise NormalizationError(
                f"Excessively stale observation rejected from {obs.source_id}: age={age}s"
            )

        # 3. Asset & Currency Normalization
        normalized_asset = obs.asset_id.strip().upper()
        normalized_quote = obs.quote_currency.strip().upper()
        if not normalized_asset or not normalized_quote:
            raise NormalizationError(f"Missing asset or quote currency from {obs.source_id}")

        # 4. Return normalized dataclass
        return PriceObservation(
            asset_id=normalized_asset,
            source_id=obs.source_id.strip(),
            source_group=obs.source_group.strip(),
            price=round(float(obs.price), 6),
            timestamp=int(obs.timestamp),
            received_at=obs.received_at,
            decimals=18,
            quote_currency=normalized_quote,
            metadata=obs.metadata
        )

    def filter_valid(self, observations: List[PriceObservation]) -> List[PriceObservation]:
        """Filters list of observations, dropping invalid ones and logging rejections."""
        valid_list = []
        for obs in observations:
            try:
                valid_list.append(self.normalize(obs))
            except NormalizationError:
                pass
        return valid_list
