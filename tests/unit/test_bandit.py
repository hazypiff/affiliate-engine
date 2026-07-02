"""Bandit correctness: censoring semantics + convergence to best-EPC arm under delay."""

import numpy as np

from engine.bandit.thompson import DEFAULT_PRIOR, ArmStats, select
from engine.sim.simulate import OfferTruth, run_sim

# Ground truth designed so the best-CONVERSION arm is NOT the best-EPC arm:
# cheap-high-conv converts most; big-payout has the highest EPC (research: revenue weighting).
TRUTHS = [
    OfferTruth(offer_id=1, conv_rate=0.08, payout=10.0, nominal_payout=10.0),   # EPC 0.80
    OfferTruth(offer_id=2, conv_rate=0.03, payout=60.0, nominal_payout=60.0),   # EPC 1.80  <- best
    OfferTruth(offer_id=3, conv_rate=0.05, payout=20.0, nominal_payout=20.0),   # EPC 1.00
]


def test_pending_clicks_never_touch_posterior():
    """The censoring proof: an arm with only pending clicks keeps its prior exactly."""
    arm = ArmStats(offer_id=1, converted=0, expired=0, pending=500, nominal_payout=25.0)
    assert arm.posterior() == DEFAULT_PRIOR
    assert arm.payout_estimate() == 25.0


def test_resolved_clicks_update_posterior():
    arm = ArmStats(offer_id=1, converted=3, expired=7, pending=100, total_revenue=90.0)
    assert arm.posterior() == (4.0, 8.0)
    assert arm.payout_estimate() == 30.0  # observed mean revenue, not nominal


def test_select_prefers_higher_ev_when_certain():
    rng = np.random.default_rng(0)
    strong = ArmStats(offer_id=1, converted=900, expired=100, total_revenue=900 * 50.0)
    weak = ArmStats(offer_id=2, converted=100, expired=900, total_revenue=100 * 5.0)
    picks = [select([strong, weak], rng) for _ in range(200)]
    assert picks.count(1) > 190


def test_convergence_to_best_epc_arm_under_delayed_censored_feedback():
    """Allocation over the last 20% of steps must go >=60% to the best-EPC arm, >=4/5 seeds."""
    wins = 0
    for seed in range(5):
        result = run_sim(TRUTHS, steps=600, arrivals_per_step=20, attribution_window=40, seed=seed)
        if result.allocation(offer_id=2, last_frac=0.2) >= 0.60:
            wins += 1
    assert wins >= 4, f"converged in only {wins}/5 seeds"


def test_sim_produces_expirations_and_conversions():
    result = run_sim(TRUTHS, steps=300, arrivals_per_step=10, attribution_window=20, seed=1)
    assert result.conversions > 0
    assert result.expired > 0
    assert result.revenue > 0
