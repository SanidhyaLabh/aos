"""
ASO Oracle Consensus Engine
Evaluates freshness, source independence, divergence spread, and produces aggregated valuations.
"""

import time
from typing import List, Optional
from dataclasses import dataclass, field
from backend.collectors.base import PriceObservation
from backend.oracle.source_registry import SourceRegistry

@dataclass
class ConsensusResult:
    success: bool
    status: str # FRESH, STALE, DIVERGENT, INSUFFICIENT_SOURCES, UNAVAILABLE
    asset_id: str
    aggregate_price: float
    min_price: float
    max_price: float
    divergence_bps: float
    source_count: int
    independent_group_count: int
    observations: List[PriceObservation]
    window_start: int
    window_end: int
    evaluated_at: int = field(default_factory=lambda: int(time.time()))
    rejection_reason: Optional[str] = None

class OracleEngine:
    def __init__(
        self,
        registry: SourceRegistry,
        max_staleness: int = 60,
        max_window: int = 60,
        max_divergence_bps: int = 50
    ):
        self.registry = registry
        self.max_staleness = max_staleness
        self.max_window = max_window
        self.max_divergence_bps = max_divergence_bps

    def evaluate_consensus(self, observations: List[PriceObservation]) -> ConsensusResult:
        now = int(time.time())

        if not observations:
            return ConsensusResult(
                success=False,
                status="UNAVAILABLE",
                asset_id="",
                aggregate_price=0.0,
                min_price=0.0,
                max_price=0.0,
                divergence_bps=0.0,
                source_count=0,
                independent_group_count=0,
                observations=[],
                window_start=now,
                window_end=now,
                rejection_reason="No observations received"
            )

        asset_id = observations[0].asset_id

        # 1. Freshness & Window evaluation
        timestamps = [obs.timestamp for obs in observations]
        window_start = min(timestamps)
        window_end = max(timestamps)

        if (now - window_end) > self.max_staleness:
            return ConsensusResult(
                success=False,
                status="STALE",
                asset_id=asset_id,
                aggregate_price=0.0,
                min_price=0.0,
                max_price=0.0,
                divergence_bps=0.0,
                source_count=len(observations),
                independent_group_count=0,
                observations=observations,
                window_start=window_start,
                window_end=window_end,
                rejection_reason=f"Observations stale: window_end was {now - window_end}s ago"
            )

        if (window_end - window_start) > self.max_window:
            return ConsensusResult(
                success=False,
                status="DIVERGENT",
                asset_id=asset_id,
                aggregate_price=0.0,
                min_price=0.0,
                max_price=0.0,
                divergence_bps=0.0,
                source_count=len(observations),
                independent_group_count=0,
                observations=observations,
                window_start=window_start,
                window_end=window_end,
                rejection_reason=f"Sampling window too wide: {window_end - window_start}s"
            )

        # 2. Source Independence & Quorum
        unique_sources = {obs.source_id for obs in observations}
        unique_groups = {obs.source_group for obs in observations}

        if len(unique_sources) < self.registry.min_sources:
            return ConsensusResult(
                success=False,
                status="INSUFFICIENT_SOURCES",
                asset_id=asset_id,
                aggregate_price=0.0,
                min_price=0.0,
                max_price=0.0,
                divergence_bps=0.0,
                source_count=len(unique_sources),
                independent_group_count=len(unique_groups),
                observations=observations,
                window_start=window_start,
                window_end=window_end,
                rejection_reason=f"Quorum failure: {len(unique_sources)} sources < required {self.registry.min_sources}"
            )

        if len(unique_groups) < self.registry.min_independent_groups:
            return ConsensusResult(
                success=False,
                status="INSUFFICIENT_SOURCES",
                asset_id=asset_id,
                aggregate_price=0.0,
                min_price=0.0,
                max_price=0.0,
                divergence_bps=0.0,
                source_count=len(unique_sources),
                independent_group_count=len(unique_groups),
                observations=observations,
                window_start=window_start,
                window_end=window_end,
                rejection_reason=f"Independence failure: {len(unique_groups)} groups < required {self.registry.min_independent_groups}"
            )

        # 3. Spread & Divergence Analysis
        prices = [obs.price for obs in observations]
        min_p = min(prices)
        max_p = max(prices)

        # Compute Liquidity-Weighted or Sorted-Median Aggregate
        sorted_prices = sorted(prices)
        n = len(sorted_prices)
        if n % 2 == 1:
            aggregate_price = sorted_prices[n // 2]
        else:
            aggregate_price = (sorted_prices[n // 2 - 1] + sorted_prices[n // 2]) / 2.0

        spread = max_p - min_p
        divergence_bps = (spread * 10000.0) / aggregate_price if aggregate_price > 0 else 0.0

        if divergence_bps > self.max_divergence_bps:
            return ConsensusResult(
                success=False,
                status="DIVERGENT",
                asset_id=asset_id,
                aggregate_price=round(aggregate_price, 4),
                min_price=round(min_p, 4),
                max_price=round(max_p, 4),
                divergence_bps=round(divergence_bps, 2),
                source_count=len(unique_sources),
                independent_group_count=len(unique_groups),
                observations=observations,
                window_start=window_start,
                window_end=window_end,
                rejection_reason=f"Divergence {divergence_bps:.1f} bps exceeds tolerance of {self.max_divergence_bps} bps"
            )

        # Successful Consensus
        return ConsensusResult(
            success=True,
            status="FRESH",
            asset_id=asset_id,
            aggregate_price=round(aggregate_price, 4),
            min_price=round(min_p, 4),
            max_price=round(max_p, 4),
            divergence_bps=round(divergence_bps, 2),
            source_count=len(unique_sources),
            independent_group_count=len(unique_groups),
            observations=observations,
            window_start=window_start,
            window_end=window_end,
            rejection_reason=None
        )
