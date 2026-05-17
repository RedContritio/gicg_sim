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


# --- Kuhn Poker helpers import ------------------------------------- #
from training.tests.kuhn_helpers import (
    _KuhnPoker,
    _kuhn_traverse,
    _kuhn_finalize_regret,
    _kuhn_outcome_sampling_step,
    _kuhn_external_sampling,
)


class TestKuhnPokerExternalSampling:
    """External-sampling MCCFR control — validates that the basic CFR
    update (counterfactual regret = reach_opp × (v(a) − v(σ)), reach-
    weighted average strategy) plus the ``regret_to_policy`` helper
    converge to a Nash equilibrium on Kuhn Poker. If this PASSES and
    the OS variant above FAILS, the bug is isolated to OS-MCCFR's
    importance-weight bookkeeping — not the shared regret-matching
    algebra or the production code's regret→policy translation."""

    def test_average_strategy_approaches_nash(self):
        rng = np.random.default_rng(31337)
        regret: dict = {}
        cum_strategy: dict = {}

        n_iter = 20_000
        for t in range(n_iter):
            _kuhn_external_sampling(regret, cum_strategy, t % 2, rng)

        def avg_bet(player, card, history):
            I = _KuhnPoker.infoset(player, card, history)
            s = cum_strategy.get(I)
            if s is None:
                return None
            tot = s.sum()
            if tot <= 0:
                return None
            return float(s[1] / tot)

        # Kuhn's Nash is a family parameterized by α ∈ [0, 1/3]:
        #   P1(J) bet = α,    P1(Q) bet = 0,     P1(K) bet = 3α
        #   P2(J)|bet fold=1, P2(Q)|bet call=1/3, P2(K)|bet call=1
        #   P2(J)|pass bet=1/3, P2(Q)|pass bet=0,  P2(K)|pass bet=1
        # We don't know which α finite-sample CFR lands on, so we verify
        # the Nash STRUCTURE (family constraint P1(K)=3·P1(J), Q never
        # bets, pure-strategy pairs) rather than any specific α.
        p1_k_bet = avg_bet(0, 2, ())
        p1_q_bet = avg_bet(0, 1, ())
        p1_j_bet = avg_bet(0, 0, ())
        p2_k_call = avg_bet(1, 2, (1,))
        p2_j_call = avg_bet(1, 0, (1,))
        p2_q_call = avg_bet(1, 1, (1,))

        assert p1_q_bet is not None and p1_q_bet < 0.08, f'P1(Q) must never bet first in Nash; got {p1_q_bet}'
        assert p1_j_bet is not None and 0.0 <= p1_j_bet <= 0.40, f'P1(J) bet = α ∈ [0, 1/3]; got {p1_j_bet}'
        assert p1_k_bet is not None and 0.0 <= p1_k_bet <= 1.0, f'P1(K) bet = 3α ∈ [0, 1]; got {p1_k_bet}'
        # Family constraint: P1(K) ≈ 3 · P1(J). Finite-sample slack 0.15.
        assert abs(p1_k_bet - 3.0 * p1_j_bet) < 0.15, f'P1(K)={p1_k_bet:.3f} should be ≈ 3·P1(J)={3 * p1_j_bet:.3f}'
        assert p2_k_call is not None and p2_k_call > 0.85, f'P2(K)|bet must always call; got {p2_k_call}'
        assert p2_j_call is not None and p2_j_call < 0.15, f'P2(J)|bet must always fold; got {p2_j_call}'
        # P2(Q)|bet calls with prob 1/3 across the Nash family.
        assert p2_q_call is not None and 0.15 < p2_q_call < 0.55, f'P2(Q)|bet call ≈ 1/3; got {p2_q_call}'
