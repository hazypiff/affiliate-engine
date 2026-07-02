"""Thompson sampling over affiliate offers with censored delayed conversions.

Pure math — no I/O, no clocks. Callers (store.py, sim) supply ArmStats built from
RESOLVED observations only: a click counts toward the posterior only once its status
is 'converted' or 'expired'. Pending clicks contribute nothing (censoring; see
research report §1.3 — the classic failure mode is counting pending as failures,
which starves slow-converting arms).

Expected-value sampling: sample p ~ Beta(prior_a + converted, prior_b + expired),
EV = p * payout, pick argmax. Payout = observed mean revenue once conversions exist,
else the offer's nominal payout_amount (the payout prior) — this makes the bandit
optimize EPC, not click-through (research correction #1).
"""

from dataclasses import dataclass

import numpy as np

DEFAULT_PRIOR = (1.0, 1.0)


@dataclass(frozen=True)
class ArmStats:
    offer_id: int
    converted: int = 0
    expired: int = 0
    pending: int = 0  # informational only; never enters the posterior
    total_revenue: float = 0.0
    nominal_payout: float = 0.0

    def posterior(self, prior: tuple[float, float] = DEFAULT_PRIOR) -> tuple[float, float]:
        a, b = prior
        return (a + self.converted, b + self.expired)

    def payout_estimate(self) -> float:
        if self.converted > 0:
            return self.total_revenue / self.converted
        return self.nominal_payout


def sample_ev(arm: ArmStats, rng: np.random.Generator, prior=DEFAULT_PRIOR) -> float:
    a, b = arm.posterior(prior)
    return float(rng.beta(a, b)) * arm.payout_estimate()


def select(arms: list[ArmStats], rng: np.random.Generator, prior=DEFAULT_PRIOR) -> int:
    """Return the offer_id with the highest sampled expected value."""
    if not arms:
        raise ValueError("select() requires at least one arm")
    best_id, best_ev = arms[0].offer_id, float("-inf")
    for arm in arms:
        ev = sample_ev(arm, rng, prior)
        if ev > best_ev:
            best_id, best_ev = arm.offer_id, ev
    return best_id
