"""
friction_engine.py — Dual-Horizon Friction Engine (DHFE)

Python mirror of the on-chain friction logic, matching the same pattern as
risk_engine.py (which mirrors RiskEngine.sol). Use this for:
  - Live simulation in terminal_backend.py (what the dashboard displays)
  - Offline calibration (calibrate_dhfe.py imports and reuses these functions)
  - Manual Risk Validator scenario scripting

All formulas are explicit and auditable — no ML, no black box. See the
accompanying explanation for the math behind each function.
"""

from dataclasses import dataclass, field
from typing import Dict


# ---------------------------------------------------------------------------
# Calibrated constants — replace these with whatever calibrate_dhfe.py outputs
# as its top-ranked (lambda, k_phi) pair. Keep them here as named constants,
# not magic numbers, so the Solidity port and the pitch deck can cite them.
# ---------------------------------------------------------------------------
DEFAULT_LAMBDA = 0.95       # EWMA decay factor (per polling interval)
DEFAULT_K_PHI = 3.0         # convexity exponent for phi(u) = u^k_phi
DEFAULT_BETA = 1.5          # friction -> rate-multiplier sensitivity


def phi(u: float, k_phi: float = DEFAULT_K_PHI) -> float:
    """
    Convex friction function. u is a utilization-like ratio in [0, 1]
    (how much of available headroom this signal is consuming).
    Returns a value in [0, 1]. Near-zero for small u, steep near u -> 1.
    """
    u = max(0.0, min(u, 1.0))
    return u ** k_phi


def instantaneous_friction(x: float, gamma: float, debt: float,
                            k_phi: float = DEFAULT_K_PHI) -> float:
    """
    f_inst(x) = phi( x / (Gamma - D) )

    x      : size of the borrow being evaluated right now
    gamma  : current manipulation-cost-anchored debt ceiling (from RiskEngine)
    debt   : current total protocol debt
    """
    headroom = max(gamma - debt, 1e-9)  # avoid divide-by-zero if D >= Gamma
    return phi(x / headroom, k_phi)


@dataclass
class ExposureTracker:
    """
    Per-address EWMA exposure tracker.
    E(t) = lambda * E(t-1) + (1 - lambda) * x_t
    """
    lam: float = DEFAULT_LAMBDA
    exposure: Dict[str, float] = field(default_factory=dict)

    def update(self, address: str, x: float) -> float:
        prev = self.exposure.get(address, 0.0)
        new_val = self.lam * prev + (1 - self.lam) * x
        self.exposure[address] = new_val
        return new_val

    def get(self, address: str) -> float:
        return self.exposure.get(address, 0.0)

    @staticmethod
    def half_life_periods(lam: float) -> float:
        """How many periods until an old exposure contribution decays to half
        its original weight. Useful for picking lambda from a target memory
        window instead of guessing: lam = 0.5 ** (1 / desired_half_life)."""
        import math
        if lam <= 0 or lam >= 1:
            raise ValueError("lambda must be in (0, 1)")
        return math.log(0.5) / math.log(lam)


def cumulative_friction(address: str, tracker: ExposureTracker, gamma: float,
                         n_active_borrowers: int, k_phi: float = DEFAULT_K_PHI) -> float:
    """
    f_cum(t) = phi( E_addr(t) / Gamma_addr ),  Gamma_addr = Gamma / N_active
    """
    gamma_addr = max(gamma / max(n_active_borrowers, 1), 1e-9)
    e_addr = tracker.get(address)
    return phi(e_addr / gamma_addr, k_phi)


def combined_friction(f_inst: float, f_cum: float) -> float:
    """
    Noisy-OR combination: either signal alone can drive friction up,
    but they don't add unboundedly past 1.
    f_final = f_inst + f_cum - f_inst * f_cum
    """
    return f_inst + f_cum - f_inst * f_cum


def effective_rate(base_rate: float, f_final: float, beta: float = DEFAULT_BETA) -> float:
    """
    effective_rate = base_rate * (1 + beta * f_final)
    """
    return base_rate * (1 + beta * f_final)


@dataclass
class FrictionEngine:
    """
    Stateful engine wrapping the functions above — this is what
    terminal_backend.py should hold one instance of and call per borrow
    request, and what the Manual Risk Validator drives with scripted inputs.
    """
    gamma: float
    debt: float
    n_active_borrowers: int
    lam: float = DEFAULT_LAMBDA
    k_phi: float = DEFAULT_K_PHI
    beta: float = DEFAULT_BETA
    tracker: ExposureTracker = field(init=False)

    def __post_init__(self):
        self.tracker = ExposureTracker(lam=self.lam)

    def evaluate_borrow(self, address: str, x: float, base_rate: float) -> dict:
        """
        Full pipeline for one borrow request. Returns everything the
        dashboard needs to render: each signal, the combined friction,
        and the resulting effective rate.
        """
        f_inst = instantaneous_friction(x, self.gamma, self.debt, self.k_phi)

        # update exposure AFTER computing f_inst on the pre-update state,
        # but the cumulative signal itself reflects exposure INCLUDING this tx,
        # so structuring is caught as soon as this tx lands, not one tx late.
        e_addr = self.tracker.update(address, x)
        f_cum = cumulative_friction(address, self.tracker, self.gamma,
                                     self.n_active_borrowers, self.k_phi)

        f_final = combined_friction(f_inst, f_cum)
        rate = effective_rate(base_rate, f_final, self.beta)

        return {
            "address": address,
            "borrow_size": x,
            "f_inst": round(f_inst, 6),
            "f_cum": round(f_cum, 6),
            "f_final": round(f_final, 6),
            "ewma_exposure": round(e_addr, 4),
            "base_rate": base_rate,
            "effective_rate": round(rate, 6),
        }


if __name__ == "__main__":
    # Quick sanity check: honest small borrower vs one-shot attacker
    # vs structured (split) attacker, against the same Gamma/debt state.
    engine = FrictionEngine(gamma=400_000, debt=100_000, n_active_borrowers=50)

    print("Honest user, single $2,000 borrow:")
    print(engine.evaluate_borrow("0xHonest", 2_000, base_rate=0.05))

    print("\nOne-shot attacker, single $250,000 borrow:")
    print(engine.evaluate_borrow("0xAttackerOneShot", 250_000, base_rate=0.05))

    print("\nStructured attacker, 10x $10,000 borrows in sequence:")
    for i in range(10):
        result = engine.evaluate_borrow("0xAttackerStructured", 10_000, base_rate=0.05)
        print(f"  borrow #{i+1}: f_final={result['f_final']}, "
              f"ewma_exposure={result['ewma_exposure']}, "
              f"effective_rate={result['effective_rate']}")
