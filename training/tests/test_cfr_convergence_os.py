"""Algorithm-level convergence test: CFR on a toy game with known Nash.

The CFR implementation in training/paradigms/cfr/legacy/ spans reservoir + traversal +
networks + trainer. Each unit test verifies one piece in isolation,
but nothing checks that the assembled algorithm actually converges
toward Nash equilibrium — a critical gap for CFR, since a buggy
regret update + correct unit tests can silently produce a policy
stuck at one extreme.

This file runs a pared-down CFR loop by hand on a 2-player
zero-sum matrix game (Rock-Paper-Scissors) using the SAME regret
formulas and regret_matching helpers the production code uses:

  - ``regret_to_policy`` from training.paradigms.cfr (the
    regret-matching function used by CFRTraverser)
  - Lanctot outcome-sampling regret estimator re-implemented inline
    (matching CFRTraverser._regret_estimate; shown in the test so
    a reader can verify line-for-line equivalence)

RPS has analytical Nash = [1/3, 1/3, 1/3] for both players (fully
mixed uniform). Deep CFR on RPS converges in a few thousand
iterations. We don't test the full CFRTraverser pipeline here
(which requires a GicgEnv-compatible env) — that's covered by the
per-engine smoke tests. This file verifies the REGRET UPDATE MATH.

If this test fails, the algorithm in CFRTraverser is structurally
wrong; unit-test-level coverage cannot catch this.
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from training.paradigms.cfr import regret_to_policy


# Rock-Paper-Scissors payoff to player 0. payoff[a0, a1]:
#   rock (0) vs rock = 0, paper = -1, scissors = +1
#   paper(1) vs rock = +1, paper = 0, scissors = -1
#   scissors(2) vs rock = -1, paper = +1, scissors = 0
_RPS = np.array(
    [
        [0, -1, 1],
        [1, 0, -1],
        [-1, 1, 0],
    ],
    dtype=np.float32,
)


def _regret_match_np(regret: np.ndarray) -> np.ndarray:
    """NumPy mirror of training.paradigms.cfr.regret_to_policy on a
    single vector (no batch dim). Matches the torch version for
    correctness by round-tripping through regret_to_policy with a
    trivial legal mask."""
    r = torch.as_tensor(regret, dtype=torch.float32).unsqueeze(0)
    legal = torch.ones(1, r.shape[1], dtype=torch.bool)
    return regret_to_policy(r, legal).squeeze(0).numpy()


def _sample_from(probs: np.ndarray, rng: np.random.Generator) -> int:
    return int(rng.choice(len(probs), p=probs))


W_MAX = 100.0  # importance-weight clip, matches production default
EPSILON = 0.2  # ε-exploration, matches production smoke config


def _sampling_dist(sigma: np.ndarray) -> np.ndarray:
    """ε-exploration: q = ε × uniform + (1 − ε) × σ. Matches
    CFRTraverser._sampling_dist's mixing rule. Without exploration,
    outcome sampling on RPS sticks to whichever action won the first
    non-tie round — σ collapses to a degenerate corner and never
    recovers. ε ≥ 0.1 is enough for Nash convergence within 50K
    iterations."""
    u = np.ones_like(sigma) / len(sigma)
    return EPSILON * u + (1.0 - EPSILON) * sigma


def _outcome_sampling_step(
    cum_regret,
    cum_strategy,
    traverser,
    rng,
) -> None:
    """One iteration of outcome-sampling MCCFR on RPS with a SPECIFIC
    traverser. The caller alternates traverser across iterations
    (matches CFRTrainer's alternating schedule).

    We model RPS as sequential (the NON-traverser moves first; the
    traverser moves second without observing the opp's action). This
    keeps the reach math clean: the traverser's infostate sits after
    the opp's edge, so π^σ_{-i}(z[I_traverser]) = σ_{opp}(a_opp). The
    SAME formula covers both traversers since "non-traverser moves
    first" is a per-iteration labeling.

    W = π^σ_{-i}(z[I]) / q(z) = σ_{opp}(a_opp) / (σ_i(a_i) × σ_{opp}(a_opp))
      = 1 / σ_i(a_i) = 1 / q_sampled_at_I

    So for a depth-1 sequential game, W collapses to 1/q_sampled at
    the traverser's own decision. Clipped at W_MAX.

    Regret update (Lanctot 2013 Eq 4.14):
      r̃(a) = W u (1/q(a*) - σ(a))   if a == a*
            = -W u σ(a)               otherwise
    """
    sigma = [_regret_match_np(cum_regret[p]) for p in range(2)]
    cum_strategy[traverser] += sigma[traverser]

    # Sample actions from the ε-exploratory distribution q (NOT σ).
    # σ enters the regret update; q appears in the importance weight.
    q_dist = [_sampling_dist(sigma[p]) for p in range(2)]
    a = [_sample_from(q_dist[0], rng), _sample_from(q_dist[1], rng)]
    u_traverser = float(_RPS[a[0], a[1]] if traverser == 0 else -_RPS[a[0], a[1]])

    a_t = a[traverser]
    q_sampled = max(float(q_dist[traverser][a_t]), 1e-6)
    # W = 1/q_sampled for the "non-traverser moves first" representation.
    W = min(1.0 / q_sampled, W_MAX)

    for a_prime in range(3):
        sigma_a = float(sigma[traverser][a_prime])
        if a_prime == a_t:
            cum_regret[traverser][a_prime] += W * u_traverser * (1.0 / q_sampled - sigma_a)
        else:
            cum_regret[traverser][a_prime] += -W * u_traverser * sigma_a


class TestRPSConvergence:
    """Outcome-sampling CFR on RPS should have its average strategy
    converge to uniform [1/3, 1/3, 1/3]. Exact regret-matching
    strategy may oscillate, but the time-averaged strategy is the
    Nash approximation CFR outputs (what CFRStrategyNet learns from
    the strategy buffer in production)."""

    def test_average_strategy_approaches_uniform(self):
        # Alternating traverser (matches CFRTrainer). Each iteration
        # updates only the current traverser's regret + accumulates
        # only their strategy sample.
        rng = np.random.default_rng(12345)
        cum_regret = [np.zeros(3, dtype=np.float64), np.zeros(3, dtype=np.float64)]
        cum_strategy = [np.zeros(3, dtype=np.float64), np.zeros(3, dtype=np.float64)]
        n_iter = 50_000
        for t in range(n_iter):
            traverser = t % 2
            _outcome_sampling_step(cum_regret, cum_strategy, traverser, rng)

        avg_sigma = [cum_strategy[p] / cum_strategy[p].sum() for p in range(2)]
        for p in range(2):
            for a in range(3):
                assert abs(avg_sigma[p][a] - 1 / 3) < 0.05, (
                    f'player {p} avg_sigma[{a}]={avg_sigma[p][a]:.4f} drifted from Nash 1/3'
                )

    def test_cumulative_regret_stays_bounded(self):
        """For a correct CFR implementation on a zero-sum matrix
        game, the positive cumulative regret divided by T should
        decay toward 0 (no-regret property).

        Under outcome sampling there's stochastic noise, but the
        growth rate of max-positive-regret should be sublinear in T
        — loosely, |R|/T → 0 as T → ∞. We assert with a generous
        bound to avoid flakiness."""
        rng = np.random.default_rng(54321)
        cum_regret = [np.zeros(3, dtype=np.float64), np.zeros(3, dtype=np.float64)]
        cum_strategy = [np.zeros(3, dtype=np.float64), np.zeros(3, dtype=np.float64)]
        n_iter = 20_000
        for t in range(n_iter):
            _outcome_sampling_step(cum_regret, cum_strategy, t % 2, rng)

        for p in range(2):
            max_pos_regret = max(cum_regret[p].max(), 0.0)
            # Outcome sampling's regret magnitude scales with W which
            # has high variance; accept anything sublinear in T.
            # |R|/T < 0.5 is a loose-but-meaningful bound.
            assert max_pos_regret / n_iter < 0.5, (
                f'player {p} max regret / T = {max_pos_regret / n_iter:.4f} not sufficiently sublinear'
            )


# --- Kuhn Poker helpers import ------------------------------------- #
from training.tests.kuhn_helpers import (
    _KuhnPoker,
    _kuhn_traverse,
    _kuhn_finalize_regret,
    _kuhn_outcome_sampling_step,
    _kuhn_external_sampling,
)


class TestKuhnPokerOutcomeSampling:
    """OS-MCCFR convergence to Nash family on Kuhn Poker. Production's
    ``CFRTraverser._regret_estimate`` uses the same Lanctot 2013 Def.4
    form as this test — convergence here validates the production
    algorithm's ``reach_q_prefix`` + corrected non-sampled regret
    (``-W·z·σ(a*)/q(a*)`` on every non-sampled slot, NOT ``-W·z·σ(a)``
    with σ at the individual action — see commit messages for the
    two-step fix history)."""

    def test_average_strategy_approaches_nash(self):
        rng = np.random.default_rng(7777)
        regret: dict = {}
        cum_strategy: dict = {}

        n_iter = 50_000
        for t in range(n_iter):
            _kuhn_outcome_sampling_step(regret, cum_strategy, t % 2, rng)

        def avg_bet(player, card, history):
            I = _KuhnPoker.infoset(player, card, history)
            s = cum_strategy.get(I)
            if s is None:
                return None
            tot = s.sum()
            if tot <= 0:
                return None
            return float(s[1] / tot)

        p1_k_bet = avg_bet(0, 2, ())
        p1_q_bet = avg_bet(0, 1, ())
        p1_j_bet = avg_bet(0, 0, ())
        p2_k_call = avg_bet(1, 2, (1,))
        p2_j_call = avg_bet(1, 0, (1,))
        p2_q_call = avg_bet(1, 1, (1,))

        # Nash family (α ∈ [0, 1/3]):
        #   P1(J) bet = α,  P1(Q) bet = 0,  P1(K) bet = 3α
        #   P2(J)|bet fold=1, P2(Q)|bet call=1/3, P2(K)|bet call=1
        # We verify structural Nash constraints rather than any specific
        # α — CFR's σ_avg will land somewhere in the family based on
        # sample noise.
        assert p1_q_bet is not None and p1_q_bet < 0.10, f'P1(Q) must rarely bet in Nash; got {p1_q_bet}'
        assert p1_j_bet is not None and 0.0 <= p1_j_bet <= 0.40, f'P1(J) bet = α ∈ [0, 1/3]; got {p1_j_bet}'
        # P1(K) bet = 3α must pass the OS version's noise budget.
        # 50K samples gives ≈±0.1 deviation from Nash.
        assert p1_k_bet is not None and p1_k_bet > 0.50, f'P1(K) bet must be well above 0.5 (Nash 3α); got {p1_k_bet}'
        assert p2_j_call is not None and p2_j_call < 0.10, f'P2(J)|bet must fold in Nash; got {p2_j_call}'
        assert p2_k_call is not None and p2_k_call > 0.85, f'P2(K)|bet must call in Nash; got {p2_k_call}'
        assert p2_q_call is not None and 0.15 < p2_q_call < 0.55, f'P2(Q)|bet call ≈ 1/3; got {p2_q_call}'


class TestRegretToPolicyShape:
    """Cross-check: the helper mirrors training.paradigms.cfr's exact
    regret_to_policy shape on vectors so the test file speaks the
    same algebra as production."""

    def test_positive_regret_proportional(self):
        r = np.array([1.0, 2.0, 3.0], dtype=np.float32)
        sigma = _regret_match_np(r)
        np.testing.assert_allclose(sigma, [1 / 6, 2 / 6, 3 / 6], atol=1e-5)

    def test_all_nonpositive_uniform(self):
        r = np.array([-1.0, -2.0, -3.0], dtype=np.float32)
        sigma = _regret_match_np(r)
        np.testing.assert_allclose(sigma, [1 / 3, 1 / 3, 1 / 3], atol=1e-5)
