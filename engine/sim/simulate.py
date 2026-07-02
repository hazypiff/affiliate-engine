"""Event-driven traffic simulator with delayed, censored conversions.

Time is an integer step counter; future postbacks sit in a heap keyed by due step.
Works against any backend implementing the small protocol below, so the same
harness drives the pure in-memory bandit (unit tests, milliseconds) and the live
HTTP tracker (e2e).
"""

import heapq
from dataclasses import dataclass, field

import numpy as np

from engine.bandit.thompson import ArmStats, select


@dataclass
class OfferTruth:
    """Ground truth for one offer in a simulation."""

    offer_id: int
    conv_rate: float
    payout: float
    nominal_payout: float  # what the config claims (bandit's payout prior)
    delay_min: int = 1
    delay_max: int = 30


@dataclass
class SimResult:
    picks: list[int] = field(default_factory=list)
    conversions: int = 0
    expired: int = 0
    revenue: float = 0.0

    def allocation(self, offer_id: int, last_frac: float = 0.2) -> float:
        tail = self.picks[int(len(self.picks) * (1 - last_frac)) :]
        if not tail:
            return 0.0
        return sum(1 for p in tail if p == offer_id) / len(tail)


class MemoryBackend:
    """In-memory censored-accounting backend mirroring the tracker's semantics."""

    def __init__(self, truths: list[OfferTruth], attribution_window: int):
        self.truths = {t.offer_id: t for t in truths}
        self.window = attribution_window
        self.stats = {
            t.offer_id: {"converted": 0, "expired": 0, "pending": 0, "revenue": 0.0}
            for t in truths
        }
        self.pending: list[tuple[int, int]] = []  # (clicked_step, offer_id) queue for expiry

    def arms(self) -> list[ArmStats]:
        return [
            ArmStats(
                offer_id=oid,
                converted=s["converted"],
                expired=s["expired"],
                pending=s["pending"],
                total_revenue=s["revenue"],
                nominal_payout=self.truths[oid].nominal_payout,
            )
            for oid, s in self.stats.items()
        ]

    def record_click(self, offer_id: int, step: int) -> None:
        self.stats[offer_id]["pending"] += 1
        heapq.heappush(self.pending, (step, offer_id))

    def record_conversion(self, offer_id: int, revenue: float) -> None:
        s = self.stats[offer_id]
        if s["pending"] > 0:
            s["pending"] -= 1
            s["converted"] += 1
            s["revenue"] += revenue

    def expire(self, now_step: int) -> None:
        # NOTE: approximate FIFO expiry — fine for simulation; the DB backend is exact per-click.
        while self.pending and self.pending[0][0] <= now_step - self.window:
            _, oid = heapq.heappop(self.pending)
            s = self.stats[oid]
            if s["pending"] > 0:
                s["pending"] -= 1
                s["expired"] += 1


def run_sim(
    truths: list[OfferTruth],
    steps: int = 600,
    arrivals_per_step: int = 20,
    attribution_window: int = 40,
    seed: int = 0,
) -> SimResult:
    rng = np.random.default_rng(seed)
    backend = MemoryBackend(truths, attribution_window)
    future: list[tuple[int, int, float]] = []  # (due_step, offer_id, revenue)
    result = SimResult()

    for step in range(steps):
        # deliver postbacks that are due
        while future and future[0][0] <= step:
            _, oid, rev = heapq.heappop(future)
            backend.record_conversion(oid, rev)
            result.conversions += 1
            result.revenue += rev
        backend.expire(step)

        for _ in range(arrivals_per_step):
            oid = select(backend.arms(), rng)
            result.picks.append(oid)
            backend.record_click(oid, step)
            truth = backend.truths[oid]
            if rng.random() < truth.conv_rate:
                delay = int(rng.integers(truth.delay_min, truth.delay_max + 1))
                if delay <= attribution_window:  # conversions past the window are censored forever
                    heapq.heappush(future, (step + delay, oid, truth.payout))

    result.expired = sum(s["expired"] for s in backend.stats.values())
    return result
