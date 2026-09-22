"""
Source Registry & Independence Verification Module
Enforces that observations satisfy multi-source quorum and independent provider groups.
"""

from typing import Dict, List, Set, Optional
from pydantic import BaseModel, Field

class SourceDefinition(BaseModel):
    source_id: str
    provider: str
    source_group: str
    data_domain: str
    asset: str
    weight: float = 1.0
    max_age_seconds: int = 60
    active: bool = True

class SourceRegistry:
    def __init__(
        self,
        default_min_sources: int = 3,
        default_min_independent_groups: int = 2,
        default_max_divergence_bps: int = 50
    ):
        self.sources: Dict[str, SourceDefinition] = {}
        self.min_sources = default_min_sources
        self.min_independent_groups = default_min_independent_groups
        self.max_divergence_bps = default_max_divergence_bps

    def register_source(self, source: SourceDefinition):
        self.sources[source.source_id] = source

    def get_source(self, source_id: str) -> Optional[SourceDefinition]:
        return self.sources.get(source_id)

    def verify_independence(self, source_ids: List[str]) -> bool:
        """
        Verifies that the provided list of source IDs satisfies:
        1. Unique source count >= min_sources
        2. Unique independent source groups >= min_independent_groups
        """
        unique_sources = set(source_ids)
        if len(unique_sources) < self.min_sources:
            return False

        unique_groups: Set[str] = set()
        for s_id in unique_sources:
            src = self.sources.get(s_id)
            if src and src.active:
                unique_groups.add(src.source_group)
            else:
                # If unregistered, treat source_id itself as a fallback group
                unique_groups.add(s_id)

        return len(unique_groups) >= self.min_independent_groups
