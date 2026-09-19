"""
Origin // ASO v3.1 — Quantitative Risk Engine & Manipulation Cost Model (Python)
Implements PART A — EXACT DEFINITIONS:
  A1. Capital to push one source (constant-product model or orderbook):
      C_cap_s(m) = R_s * (sqrt(1+m) - 1) if tradable_s else infinity
  A2. Weights over available reporting sources only:
      w'_s = w_s / sum(w_reporting)
  A3. Coalition cost to move weighted median (sum w'_s >= 0.5):
      Independence groups: merged into one node (combined weight, upstream depth)
      C_cap_med(m) = min over S (sum w'_s >= 0.5) of sum C_cap_s(m)
  A4. Net cost: C_net(m) = rho * C_cap_med(m) (rho measured from Part D = 0.1412)
  A5. Extractable value:
      E_borrow(m) = LTV * V * m
      E_loss(m)   = max(0, B - V_true * (1 - d))
  A6. Cap:
      Gamma = k * C_net(mRef) / mRef
      debtCeilingAsset = min(configuredCeiling, Gamma)
      epochGrowthCap   = g * Gamma
  A7. Two known holes closed:
      (i) Slow ratchet anchor: measure m against 24h slow anchor with max drift rate per epoch
      (ii) Fake depth: compute Gamma from MINIMUM depth seen over last 12 cycles
"""

import math
from typing import Dict, List, Tuple, Optional

class Source:
    def __init__(
        self,
        source_id: str,
        name: str,
        weight: float,          # Weight in bps (e.g. 3500 = 35%)
        quote_depth: float,     # R_s in USD
        is_tradable: bool,      # True for DEX/CEX orderbook, False for untradable indices
        upstream_group: int,    # Sources sharing upstream feed share group ID (>0)
        source_type: str = "Spot"
    ):
        self.id = source_id
        self.name = name
        self.weight = weight
        self.quote_depth = quote_depth
        self.is_tradable = is_tradable
        self.upstream_group = upstream_group
        self.source_type = source_type
        self.is_reporting = True
        self.price = 100.0
        # A7.ii: Ring buffer of last 12 cycles depth
        self.depth_history = [quote_depth] * 12
        self.depth_index = 0

    def record_depth(self, depth: float):
        self.quote_depth = depth
        self.depth_history[self.depth_index] = depth
        self.depth_index = (self.depth_index + 1) % 12

    def get_min_recent_depth(self) -> float:
        """A7.ii: Returns minimum depth seen over last 12 cycles."""
        if not self.is_tradable:
            return 0.0
        return min(self.depth_history)


class RiskEnginePython:
    def __init__(
        self,
        rho: float = 0.1412,          # Measured net-loss ratio from Part D (14.12%)
        k_factor: float = 0.10,       # Safety factor k = 0.10 (chosen below 5th percentile rho)
        m_ref: float = 0.15,          # 15% largest defended move
        epoch_growth_share: float = 0.20, # g = 20% epoch growth cap
        configured_ceiling: float = 1_000_000.0, # Baseline $1M configured ceiling
        collateral_value: float = 1_000_000.0,   # V = $1,000,000 honest collateral
        ltv: float = 0.80,            # 80% LTV
        liquidation_discount: float = 0.05       # d = 5% liquidation discount
    ):
        self.rho = rho
        self.k_factor = k_factor
        self.m_ref = m_ref
        self.epoch_growth_share = epoch_growth_share
        self.configured_ceiling = configured_ceiling
        self.collateral_value = collateral_value
        self.ltv = ltv
        self.liquidation_discount = liquidation_discount

        # A7.i: Slow Ratchet Anchor
        self.slow_anchor_price = 100.0
        self.max_drift_per_epoch = 0.01 # 1.00% max drift per epoch

        # Default Benchmark Sources
        # Sized so coalition depth produces realistic DeFi protocol defense metrics
        self.sources: Dict[str, Source] = {
            "ondo": Source("ondo", "Ondo RWA NAV", 3500, 350_000.0, True, 1, "RWA Custodian NAV"),
            "coinbase": Source("coinbase", "Coinbase Prime", 4000, 400_000.0, True, 2, "Institutional Spot"),
            "kraken": Source("kraken", "Kraken Treasury", 1500, 150_000.0, True, 3, "Orderbook"),
            "fed": Source("fed", "Fed H.15", 1000, 0.0, False, 4, "Interbank Reference")
        }

    # -------------------------------------------------------------------------
    # A1. Capital to push one source
    # -------------------------------------------------------------------------
    def cost_cap_single(self, source_id: str, m: float) -> float:
        """
        C_cap_s(m) = R_s * (sqrt(1+m) - 1) if tradable_s else infinity
        Uses A7.ii minimum recent depth over 12 cycles.
        """
        source = self.sources.get(source_id)
        if not source or not source.is_tradable:
            return float("inf")
        
        r_s = source.get_min_recent_depth()
        if r_s <= 0 or m <= 0:
            return 0.0
        
        return r_s * (math.sqrt(1.0 + m) - 1.0)

    # -------------------------------------------------------------------------
    # A2. Normalized weights over reporting sources
    # -------------------------------------------------------------------------
    def get_normalized_weights(self) -> Dict[str, float]:
        """w'_s = w_s / sum of w over sources currently reporting"""
        reporting_sources = [s for s in self.sources.values() if s.is_reporting]
        total_w = sum(s.weight for s in reporting_sources)
        if total_w == 0:
            return {}
        return {s.id: s.weight / total_w for s in reporting_sources}

    # -------------------------------------------------------------------------
    # A3. Coalition cost to move the weighted median
    # -------------------------------------------------------------------------
    def cost_cap(self, m: float) -> Tuple[float, List[str]]:
        """
        Brute-force all subsets S such that sum_{s in S} w'_s >= 0.5.
        Independence groups: sources sharing upstream group share depth / merged into one node.
        C_cap_med(m) = min over S (sum w'_s >= 0.5) of sum C_cap_s(m)
        """
        reporting = [s for s in self.sources.values() if s.is_reporting]
        n = len(reporting)
        if n == 0:
            return float("inf"), []

        norm_weights = self.get_normalized_weights()
        min_cost = float("inf")
        best_coalition: List[str] = []

        subsets_count = 1 << n
        for mask in range(1, subsets_count):
            subset = [reporting[i] for i in range(n) if (mask & (1 << i))]
            subset_weight = sum(norm_weights[s.id] for s in subset)

            if subset_weight >= 0.5:
                # Calculate cost, avoiding double-counting merged upstream groups
                handled_groups = set()
                cost_sum = 0.0
                impossible = False

                for s in subset:
                    if s.upstream_group not in handled_groups:
                        handled_groups.add(s.upstream_group)
                        c = self.cost_cap_single(s.id, m)
                        if math.isinf(c):
                            impossible = True
                            break
                        cost_sum += c

                if not impossible and cost_sum < min_cost:
                    min_cost = cost_sum
                    best_coalition = [s.id for s in subset]

        return min_cost, best_coalition

    # -------------------------------------------------------------------------
    # A4. Net Cost
    # -------------------------------------------------------------------------
    def cost_net(self, m: float) -> float:
        """C_net(m) = rho * C_cap_med(m)"""
        c_cap, _ = self.cost_cap(m)
        if math.isinf(c_cap):
            return float("inf")
        return self.rho * c_cap

    # -------------------------------------------------------------------------
    # A5. Extractable Value
    # -------------------------------------------------------------------------
    def extractable_borrow(self, m: float) -> float:
        """E_borrow(m) = LTV * V * m"""
        return self.ltv * self.collateral_value * m

    def extractable_loss(self, m: float, borrowed: float, v_true: Optional[float] = None) -> float:
        """E_loss(m) = max(0, B - V_true * (1 - d)), B <= LTV * V * (1 + m)"""
        if v_true is None:
            v_true = self.collateral_value
        max_borrow = self.ltv * self.collateral_value * (1.0 + m)
        b = min(borrowed, max_borrow)
        return max(0.0, b - v_true * (1.0 - self.liquidation_discount))

    # -------------------------------------------------------------------------
    # A6. Dynamic Bounded Loss Caps
    # -------------------------------------------------------------------------
    def gamma(self) -> float:
        """
        Gamma = k * C_net(mRef) / mRef
        debtCeilingAsset = min(configuredCeiling, Gamma)
        """
        c_net_ref = self.cost_net(self.m_ref)
        if math.isinf(c_net_ref):
            return self.configured_ceiling
        
        raw_gamma = (self.k_factor * c_net_ref) / self.m_ref
        return min(self.configured_ceiling, raw_gamma)

    def epoch_growth_cap(self) -> float:
        """epochGrowthCap = g * Gamma"""
        return self.epoch_growth_share * self.gamma()

    # -------------------------------------------------------------------------
    # Attack Economics
    # -------------------------------------------------------------------------
    def attack_economics(self, m: float) -> Dict:
        """
        Computes (attackerNetCost, E_borrow, netResult, margin, coalitionChosen)
        Invariant: E_borrow(m) <= Gamma * m <= k * C_net(m) < C_net(m)
        """
        c_cap, coalition = self.cost_cap(m)
        attacker_net_cost = self.rho * c_cap if not math.isinf(c_cap) else float("inf")
        max_extra_borrow = self.extractable_borrow(m)

        if math.isinf(attacker_net_cost):
            net_result = -float("inf")
            margin = 999.9
        else:
            net_result = max_extra_borrow - attacker_net_cost
            margin = (attacker_net_cost / max_extra_borrow) if max_extra_borrow > 0 else 999.9

        # Convert to displayable values
        return {
            "m": m,
            "mBps": int(m * 10000),
            "attackerNetCost": attacker_net_cost,
            "maxExtraBorrow": max_extra_borrow,
            "netResult": net_result,
            "margin": margin,
            "coalitionChosen": coalition,
            "isAttackUnprofitable": net_result <= 0
        }

    # -------------------------------------------------------------------------
    # A7.i Slow Ratchet Anchor Update
    # -------------------------------------------------------------------------
    def update_slow_anchor(self, spot_price: float) -> float:
        """
        Measures m against a slow anchor (24h average) with maximum drift rate per epoch.
        """
        max_drift = self.slow_anchor_price * self.max_drift_per_epoch
        if spot_price > self.slow_anchor_price + max_drift:
            self.slow_anchor_price += max_drift
        elif spot_price < self.slow_anchor_price - max_drift:
            self.slow_anchor_price -= max_drift
        else:
            self.slow_anchor_price = spot_price
        return self.slow_anchor_price

    # -------------------------------------------------------------------------
    # Liquidity-Weighted Median across sources
    # -------------------------------------------------------------------------
    def calculate_weighted_median(self) -> float:
        reporting = [s for s in self.sources.values() if s.is_reporting]
        if not reporting:
            return 100.0
        
        sorted_sources = sorted(reporting, key=lambda s: s.price)
        total_w = sum(s.weight for s in sorted_sources)
        half_w = total_w / 2.0

        cum = 0.0
        for s in sorted_sources:
            cum += s.weight
            if cum > half_w:
                return round(s.price, 4)
        return round(sorted_sources[-1].price, 4)
