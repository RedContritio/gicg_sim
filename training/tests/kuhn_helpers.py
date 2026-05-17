"""Kuhn Poker + shared numpy helpers for CFR convergence tests.

Not a test module (no leading ``test_`` prefix). Extracts what would
otherwise be duplicated between ``test_cfr_convergence_os.py`` and
``test_cfr_convergence_es.py``.
"""

from __future__ import annotations

import numpy as np
import torch

from training.paradigms.cfr import regret_to_policy


def _regret_match_np(regret: np.ndarray) -> np.ndarray:
    """NumPy mirror of training.paradigms.cfr.regret_to_policy on a
    single vector (no batch dim)."""
    r = torch.as_tensor(regret, dtype=torch.float32).unsqueeze(0)
    legal = torch.ones(1, r.shape[1], dtype=torch.bool)
    return regret_to_policy(r, legal).squeeze(0).numpy()


W_MAX = 100.0
EPSILON = 0.2


# --------------------------------------------------------------------------- #
# Kuhn Poker convergence (depth ≥ 2, EXERCISES production W formula).
#
# RPS collapses W = reach_opp_pre / reach_q_full to a single-node form — it
# doesn't exercise the path-level reach accumulation in CFRTraverser's
# production code. Kuhn Poker has depth-2 sequential decisions with a
# chance prefix, and actually uses:
#   reach_opp_pre = σ_opp of decisions BEFORE the current info set
#   reach_q_full  = Π q(edge) over the ENTIRE trajectory from root
# If the W formula in traversal.py is wrong, this test diverges.
#
# Game spec:
#   3 cards {J=0, Q=1, K=2}. Each player gets 1 card; 1 card discarded.
#   P1 acts first: 0=pass, 1=bet.
#     If P1 passes:
#       P2 acts: 0=pass (showdown), 1=bet.
#         If P2 bets: P1 acts: 0=fold (P2 wins 1), 1=call (showdown 2).
#     If P1 bets:
#       P2 acts: 0=fold (P1 wins 1), 1=call (showdown 2).
#   Showdown: higher card wins the pot.
#
# Nash (analytical, one member of the Nash family with α = 1/3):
#   P1 info J: bet with prob α = 1/3    (at infoset "P1 with J, no history")
#   P1 info Q: never bet first                         (P2 bet → call prob 1/3)
#   P1 info K: bet with prob 3α = 1                    (bet 3×)
#   P2 after P1 bet: J→fold, Q→call 1/3, K→call 1
#   P2 after P1 pass: J→never bet, Q→bet 1/3, K→always bet
# P1 game value = -1/18 ≈ -0.0556.
#
# The test samples deal+traversal, accumulates regret via the same Lanctot
# formula used in training/paradigms/cfr/legacy/traversal/ (with path reach tracking),
# then verifies the AVERAGE strategy at a subset of info sets converges.


class _KuhnPoker:
    """Minimal Kuhn Poker trajectory generator. Each sample() returns
    (deal, history_tuple, terminal_utility_for_P0)."""

    CARDS = [0, 1, 2]  # J, Q, K

    @staticmethod
    def infoset(player: int, card: int, history: tuple) -> tuple:
        """Infoset key: (player, card, history so far)."""
        return (player, card, history)

    @staticmethod
    def acting_player(history: tuple) -> int:
        """Who acts next. None if terminal."""
        # history is a tuple of actions (0 or 1) in play order
        if len(history) == 0:
            return 0  # P1 (we call them P0)
        if len(history) == 1:
            return 1  # P2
        if len(history) == 2:
            if history == (0, 1):
                return 0  # P1 decides fold/call after P1 pass + P2 bet
            return None  # terminal
        return None

    @staticmethod
    def terminal_utility(deal, history: tuple) -> float:
        """Utility for P0. deal = (card_p0, card_p1)."""
        c0, c1 = deal
        if history == (0, 0):
            # both pass, showdown for 1 chip
            return 1.0 if c0 > c1 else -1.0
        if history == (0, 1, 0):
            # P1 pass, P2 bet, P1 fold
            return -1.0
        if history == (0, 1, 1):
            # P1 pass, P2 bet, P1 call — showdown for 2 chips
            return 2.0 if c0 > c1 else -2.0
        if history == (1, 0):
            # P1 bet, P2 fold
            return 1.0
        if history == (1, 1):
            # P1 bet, P2 call — showdown for 2
            return 2.0 if c0 > c1 else -2.0
        raise ValueError(f'non-terminal history: {history}')


def _kuhn_traverse(
    deal,
    history,
    traverser,
    reach_i,
    reach_opp,
    sample_prob,
    regret,
    cum_strategy,
    rng,
    decisions,
):
    """Two-pass outcome-sampling MCCFR traversal matching the
    production implementation at ``training/paradigms/cfr/legacy/traversal/``
    (``_regret_estimate`` / Lanctot 2013 Eq 4.14 canonical form).

    Phase 1 (this function, recursive): sample a trajectory z and
    record each infoset's state at visit time into ``decisions``.

    Phase 2 (``_kuhn_finalize_regret`` below): given the full path's
    ``reach_q_full`` computed at terminal, apply the canonical
    regret formula at each recorded traverser infoset:

        W_I = reach_opp_pre(I) / reach_q_full
        r̃(I, a_sampled) = W_I × z × (1/q_sampled − σ(a_sampled))
        r̃(I, a ≠ a_sampled) = -W_I × z × σ(a)

    where z is the terminal utility from the traverser's perspective
    (raw ±1 / ±2, not IS-adjusted — the W factor carries the
    importance correction). This matches
    ``CFRTraverser._regret_estimate`` byte-for-byte.

    Previous test formulations (a) used ``(1 − σ)`` for sampled
    without the 1/q factor, and (b) used ``−σ(a_prime)`` for
    non-sampled — which is the correct form of the second expression
    but the first was inconsistent, breaking the
    ``Σ_a σ(a) · r(a) = 0`` property and locking σ at one-hot corners.
    See subagent analysis in commit message.
    """
    actor = _KuhnPoker.acting_player(history)
    if actor is None:
        u_p0 = _KuhnPoker.terminal_utility(deal, history)
        z = u_p0 if traverser == 0 else -u_p0
        return z, sample_prob  # return raw terminal z + full s(z)

    card = deal[actor]
    I = _KuhnPoker.infoset(actor, card, history)
    r = regret.get(I, np.zeros(2, dtype=np.float64))
    sigma = _regret_match_np(r.astype(np.float32)).astype(np.float64)

    if actor == traverser:
        # Reach-weighted average strategy: π_i(I) / s(I) × σ.
        # Using sample_prob (prefix q-path to I) matches production's
        # single-sample IS-weighted strategy accumulator.
        cum_strategy[I] = cum_strategy.get(I, np.zeros(2, dtype=np.float64)) + (reach_i / sample_prob) * sigma

    if actor == traverser:
        q = EPSILON * 0.5 + (1.0 - EPSILON) * sigma
    else:
        q = sigma
    # Renormalize to shed float drift — regret_to_policy's torch→numpy
    # round-trip occasionally yields ~1e-8 deviation from sum-to-1.
    q = q / q.sum()

    a = int(rng.choice(2, p=q))
    q_s = float(q[a])

    if actor == traverser:
        # Record this traverser infoset with its PREFIX reach_opp
        # (before descending through the action's opp segment) AND
        # its q-prefix (sample_prob TO the infoset, excluding q(a*)
        # at this node and everything after). The per-decision
        # q-prefix is the canonical W denominator in Lanctot Eq 4.14;
        # using terminal reach_q_full double-counts q(a*).
        decisions.append(
            {
                'I': I,
                'sigma': sigma,
                'sampled_a': a,
                'q_sampled': q_s,
                'reach_opp_pre': reach_opp,
                'reach_q_prefix': sample_prob,
            }
        )
        z, reach_q_full = _kuhn_traverse(
            deal,
            history + (a,),
            traverser,
            reach_i * float(sigma[a]),
            reach_opp,
            sample_prob * q_s,
            regret,
            cum_strategy,
            rng,
            decisions,
        )
        return z, reach_q_full
    else:
        z, reach_q_full = _kuhn_traverse(
            deal,
            history + (a,),
            traverser,
            reach_i,
            reach_opp * float(sigma[a]),
            sample_prob * q_s,
            regret,
            cum_strategy,
            rng,
            decisions,
        )
        return z, reach_q_full


def _kuhn_finalize_regret(decisions, z, reach_q_full, regret, W_max=100.0):
    """Phase-2 regret update using the corrected Lanctot 2013 Def.4
    form: r̃(I,a) = ṽ(σ_{I→a}, I|z) − ṽ(σ, I|z).

    For the sampled action a* (path passed through it):
      ṽ(σ_{I→a*}, I|z) = B · 1                      ... σ forced to 1 at I
      ṽ(σ, I|z)        = B · σ(a*|I)                ... σ's own prob
      r̃(I, a*) = B · (1 − σ(a*|I))

    For non-sampled a ≠ a* (path does NOT pass through a, so σ_{I→a}
    gives zero reach):
      ṽ(σ_{I→a}, I|z) = 0
      r̃(I, a)        = 0 − B · σ(a*|I) = −B · σ(a*|I)

    Note the non-sampled regret uses σ(a*|I) — the **sampled** action's
    σ — NOT σ(a|I). Earlier code used σ(a|I) which breaks Σ σ·r = 0
    at Nash and caused the ε-exploration fallback to lock σ at uniform
    (all-negative regret → regret_to_policy returns uniform).

    B = W · z / q(a*) absorbs the IS correction. W = reach_opp_pre /
    reach_q_prefix is the per-infoset prefix ratio (subagent fix, see
    commit e05b713)."""
    for dec in decisions:
        q_prefix = max(dec['reach_q_prefix'], 1e-12)
        W = min(dec['reach_opp_pre'] / q_prefix, W_max)
        sigma = dec['sigma']
        a = dec['sampled_a']
        q_floor = max(dec['q_sampled'], 1e-6)
        sigma_a_sampled = float(sigma[a])
        # Non-sampled: all slots get -W·z·σ(a*)/q(a*)
        r_delta = np.full_like(sigma, -W * z * sigma_a_sampled / q_floor)
        # Sampled: W·z·(1 − σ(a*))/q(a*)
        r_delta[a] = W * z * (1.0 - sigma_a_sampled) / q_floor
        regret[dec['I']] = regret.get(dec['I'], np.zeros(2, dtype=np.float64)) + r_delta


def _kuhn_outcome_sampling_step(
    regret,
    cum_strategy,
    traverser,
    rng,
) -> None:
    """One iteration: uniform chance deal + two-pass OS-MCCFR traverse.
    Phase 1 samples the trajectory and records decisions; phase 2
    applies the canonical Lanctot 2013 Eq 4.14 regret update."""
    deal_idx = int(rng.choice(6))
    deals_all = [(a, b) for a in _KuhnPoker.CARDS for b in _KuhnPoker.CARDS if a != b]
    deal = deals_all[deal_idx]

    decisions: list = []
    z, reach_q_full = _kuhn_traverse(
        deal,
        (),
        traverser,
        reach_i=1.0,
        reach_opp=1.0 / 6.0,
        sample_prob=1.0 / 6.0,
        regret=regret,
        cum_strategy=cum_strategy,
        rng=rng,
        decisions=decisions,
    )
    _kuhn_finalize_regret(decisions, z, reach_q_full, regret)


def _kuhn_external_sampling(
    regret,
    cum_strategy,
    traverser,
    rng,
    reach_opp=1.0,
    history=None,
    deal=None,
) -> float:
    """External-sampling MCCFR on Kuhn Poker (well-known, simpler than
    outcome sampling). Enumerates all traverser actions at each of
    their decision nodes; samples exactly one for chance and for
    opponent. Returns counterfactual value for traverser from this
    subtree.

    Used as a CONTROL: if this converges to Nash on Kuhn Poker, the
    basic CFR + regret-matching algebra (shared with CFRTraverser)
    is correct; failure to converge on outcome sampling variant is
    then attributable to OS-specific importance-weight bookkeeping.
    """
    if history is None:
        history = ()
    if deal is None:
        # Chance node at root: sample a deal
        deals_all = [(a, b) for a in _KuhnPoker.CARDS for b in _KuhnPoker.CARDS if a != b]
        deal = deals_all[int(rng.choice(6))]

    actor = _KuhnPoker.acting_player(history)
    if actor is None:
        u_p0 = _KuhnPoker.terminal_utility(deal, history)
        return u_p0 if traverser == 0 else -u_p0

    card = deal[actor]
    I = _KuhnPoker.infoset(actor, card, history)
    r = regret.get(I, np.zeros(2, dtype=np.float64))
    sigma = _regret_match_np(r.astype(np.float32)).astype(np.float64)

    if actor == traverser:
        cum_strategy[I] = cum_strategy.get(I, np.zeros(2, dtype=np.float64)) + reach_opp * sigma
        # Enumerate all actions
        action_vals = np.zeros(2, dtype=np.float64)
        for a in range(2):
            action_vals[a] = _kuhn_external_sampling(
                regret,
                cum_strategy,
                traverser,
                rng,
                reach_opp=reach_opp,
                history=history + (a,),
                deal=deal,
            )
        expected_val = float(sigma @ action_vals)
        # Counterfactual regret: r(a) += reach_opp * (v(a) - v(σ))
        r_delta = reach_opp * (action_vals - expected_val)
        regret[I] = regret.get(I, np.zeros(2, dtype=np.float64)) + r_delta
        return expected_val
    else:
        # Opponent: sample one action, propagate with reach_opp *= σ[a].
        # Renormalize sigma before rng.choice — regret_to_policy may
        # return a distribution with ~1e-7 drift from exact 1.0 which
        # numpy rejects.
        p = sigma / sigma.sum()
        a = int(rng.choice(2, p=p))
        return _kuhn_external_sampling(
            regret,
            cum_strategy,
            traverser,
            rng,
            reach_opp=reach_opp * float(sigma[a]),
            history=history + (a,),
            deal=deal,
        )
