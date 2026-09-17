"""Feature-based greedy baseline player — evaluation opponent tiers.

Not a trained agent. At each decision, simulate every legal action
via snapshot/restore, score the resulting state using a hand-crafted
feature function, and pick the argmax. Variants span a feature axis
(what to score) × a depth axis (how many plies to look ahead).

Why this exists: "random" isn't a stable baseline in complex TCG —
random play occasionally stumbles into strong moves. Greedy tiers
give a configurable opponent ladder across feature sets and search
depths. The variants are intended to become stronger with added features
or depth, although the heuristics do not guarantee a strict ordering.
They also let us
falsify "random is weak" hypotheses: if F1-D1 crushes random, random
is a weaker baseline than it looks and raw vs-random scores need
context.

## Feature variants

Both F1/F2 compute from ``env.export_view()`` HP + alive_count
deltas; F3-F5 layer RewardEvents accumulator deltas on top for
signals the view doesn't expose (shield / reaction / energy / AP).

- **F1 minimal**: ``delta_enemy_hp - 1.1 * delta_own_hp``
  (asymmetric damage; matches the final PPO-to-AZ minimal reward
  before it was stripped)
- **F2 +kill**: F1 + ``10.0 * (enemy alive_count decreased) - 8.0 * (own alive_count decreased)``
  (flat kill_base, no escalation — escalation lives in F5)
- **F3 +heal**: F2 + ``heal_done - 0.8 * enemy_heal_done`` (from
  RewardEvents; asymmetric weight so my heals beat opponent heals)
- **F4 +shield/reaction**: F3 + ``shield_absorbed - 0.8 *
  damage_blocked + reactions_triggered - 0.8 * reactions_received``
- **F5 full**: F4 + ``- 0.4 * energy_overflow - ap_waste_piecewise
  + escalating_kill_slope``

## Scorer signature

All scorers take ``(view_before, view_after, events_before,
events_after, me)``. F1/F2 ignore the events args; F3+ consume them.
Uniform signature keeps SCORERS dict-addressable and
``_score_best_response`` agnostic to which scorer is active.

``events_*`` are ``np.ndarray[14]`` aligned with
``gicg_env._constants.REWARD_EVENTS_FIELDS`` — access by index via
the ``EV_*`` module constants below.

## Depth variants

- **D1 NPC**: straight argmax over my-side score; opponent unmodeled
- **D2 adversarial 2-ply**: for each my action, opponent picks its
  D1 best response with the same feature function (from its
  perspective); I pick the my action whose resulting state scores
  highest after opponent response
- **Dn minimax**: recursively alternate max on my turns and min on the
  opponent's turns for ``n`` plies. The public configuration accepts
  depths 1 through 4.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

import numpy as np

from gicg_env import GicgEnv
from training.core.matchup.greedy_scorers import SCORERS, ScorerFn
from training.core.matchup.greedy_reroll import reroll_choice


@dataclass
class GreedyConfig:
    features: str  # 'F1' | 'F2' | 'F3' | 'F4' | 'F5'
    depth: int  # 1 | 2 | 3 | 4


def _candidate_indices(env: GicgEnv, dice_greedy: bool) -> list[int]:
    """Return the list of action indices to simulate at the current
    state. With ``dice_greedy=True`` we collapse the engine's full
    payment fan-out to one top-1 payment per logical (kind, refs)
    group (see greedy_dice.filter_logical_actions); otherwise we
    return every legal action index. Used by both select_action and
    _score_best_response — opponent's legal expansion also benefits
    from the filter since this is a symmetric wall-time speedup."""
    kinds, _ = env.get_legal_actions()
    if dice_greedy:
        from training.core.matchup.greedy_dice import filter_logical_actions

        return filter_logical_actions(env)
    return list(range(len(kinds)))


def _score_best_response(
    env: GicgEnv,
    view_root: dict,
    events_root: np.ndarray,
    me: int,
    scorer: ScorerFn,
    depth: int,
    dice_greedy: bool,
    budget: Optional[list[int]] = None,
) -> float:
    """Recursive core: score the CURRENT env state from ``me`` perspective,
    looking ahead ``depth`` more plies. Depth==0 means score the delta
    between (view_root, events_root) (pre this entire subtree) and env now.

    Important: env must be left in the same state it was on entry
    (caller handles snapshot/restore bracketing).

    ``budget`` — minimax node budget shared across the whole select_action
    call (mutable counter via single-element list). ``None`` = unbounded.
    ``budget[0] <= 0`` → stop expanding, score current node. Mirrors Go
    ``gicg_actor/dmc/greedy_player.go`` ``scoreBestResponse`` semantics for
    cross-language fair benchmarking (budget consumed per candidate snapshot
    on both sides)."""
    choice = None if env.done else reroll_choice(env)
    if choice is not None:
        snap = env.snapshot()
        try:
            while choice is not None:
                env.step(choice)
                choice = None if env.done else reroll_choice(env)
            return _score_best_response(env, view_root, events_root, me, scorer, depth, dice_greedy, budget)
        finally:
            env.restore(snap)
            env.snapshot_free(snap)
    if env.done or depth <= 0 or (budget is not None and budget[0] <= 0):
        return scorer(view_root, env.export_view(), events_root, env.reward_events(me), me)
    acting = env.acting_player
    candidates = _candidate_indices(env, dice_greedy)
    if len(candidates) == 0:
        return scorer(view_root, env.export_view(), events_root, env.reward_events(me), me)
    best: float | None = None
    for a in candidates:
        if budget is not None:
            budget[0] -= 1
        snap = env.snapshot()
        try:
            env.step(a)
            sub = _score_best_response(env, view_root, events_root, me, scorer, depth - 1, dice_greedy, budget)
        finally:
            env.restore(snap)
            env.snapshot_free(snap)
        if best is None:
            best = sub
        elif acting == me:
            best = max(best, sub)
        else:
            best = min(best, sub)
    return float(best) if best is not None else 0.0


class GreedyPlayer:
    """Feature-based lookahead. See module docstring for variants.

    Contract: ``select_action(env)`` does not permanently mutate env —
    every speculative step is bracketed by snapshot/restore. ``env.log_suspend``
    silences the replay log during simulation; restored on exit."""

    def __init__(
        self,
        features: str = 'F1',
        depth: int = 1,
        seed: int = 0,
        dice_greedy: bool = False,
        minimax_node_budget: Optional[int] = None,
    ):
        if features not in SCORERS:
            raise ValueError(f'unknown features {features!r}; known: {sorted(SCORERS)}')
        if depth not in (1, 2, 3, 4):
            raise ValueError(f'depth must be 1|2|3|4, got {depth}')
        if minimax_node_budget is not None and minimax_node_budget <= 0:
            raise ValueError(f'minimax_node_budget must be > 0 or None, got {minimax_node_budget}')
        self.cfg = GreedyConfig(features=features, depth=depth)
        self.scorer = SCORERS[features]
        self.rng = random.Random(seed)
        # dice_greedy: collapse engine payment fan-out via hand-
        # crafted dice-value heuristic (5-30× speedup on decision-
        # heavy configs). Off by default to preserve the exhaustive
        # payment expansion used by earlier evaluations.
        self.dice_greedy = dice_greedy
        # minimax_node_budget — cap total snapshot/step descents across one
        # select_action call (None = unbounded, default). Set explicitly for
        # cross-language fair bench parity with Go ``gicg_actor/dmc/
        # greedy_player.go`` (Go side accepts same knob via DMCConfig.
        # OpponentMix.MinimaxNodeBudget). D4 + dice_greedy O(N^4) without cap
        # can be expensive without a cap. Using the same explicit budget
        # on Python and Go keeps cross-language benchmarks comparable.
        self.minimax_node_budget = minimax_node_budget

    def select_action(self, env: GicgEnv) -> int:
        """Pick one action by score-argmax with random tiebreak."""
        action, _ = self.select_with_info(env)
        return action

    def select_with_info(self, env: GicgEnv) -> tuple[int, dict]:
        """Return (picked_action, info) where info has:
        - scored: list[(action, score)] for every candidate
        - tied:   list[action] sharing the best score (soft-target BC)
        - best_score: float

        BC data collection + diagnostic tools use this to record the
        tied set (for soft-target learning that doesn't fight the
        teacher's random tiebreak)."""
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            raise RuntimeError('GreedyPlayer: env has no legal actions')
        choice = reroll_choice(env)
        if choice is not None:
            return choice, {'scored': [(choice, 0.0)], 'tied': [choice], 'best_score': 0.0}
        candidates = _candidate_indices(env, self.dice_greedy)
        if len(candidates) == 0:
            raise RuntimeError('GreedyPlayer: no candidate actions after dice-filter')
        me = env.acting_player
        view_root = env.export_view()
        events_root = env.reward_events(me)
        scored: list[tuple[int, float]] = []
        # budget — single-element list as mutable counter, shared across all
        # candidates' subtrees within this select_action call (mirrors Go
        # ``SelectAction`` line ``budget := minimaxNodeBudget``). None = unbounded.
        budget: Optional[list[int]] = [self.minimax_node_budget] if self.minimax_node_budget is not None else None
        env.log_suspend()
        try:
            for a in candidates:
                if budget is not None:
                    budget[0] -= 1
                snap = env.snapshot()
                try:
                    env.step(a)
                    s = _score_best_response(
                        env,
                        view_root,
                        events_root,
                        me,
                        self.scorer,
                        self.cfg.depth - 1,
                        self.dice_greedy,
                        budget,
                    )
                finally:
                    env.restore(snap)
                    env.snapshot_free(snap)
                scored.append((a, s))
        finally:
            env.log_resume()
        best = max(s for _, s in scored)
        # Pick randomly among exact ties to avoid a fixed action-order bias.
        tied = [a for a, s in scored if s == best]
        return self.rng.choice(tied), {'scored': scored, 'tied': tied, 'best_score': best}
