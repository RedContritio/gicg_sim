"""Inference-time search augmentation for semantic-Q checkpoints.

``SearchPlayer`` wraps an already-loaded ``SemanticAgent`` (with an
attached value head, see ``value_baseline.py``) and, at each decision,
scores candidate actions by expectation over sampled hidden information:

1. Enumerate candidate actions (``greedy_dice.filter_logical_actions``
   payment-collapse first, full legal list as fallback).
2. For each candidate, average over ``n_beliefs`` determinizations:
   restore the root snapshot, sample a plausible hidden state for the
   opponent (hand / deck / dice colors) from *public* information only
   (``az.determinize.sample_hidden_state``), inject it
   (``apply_determinization``), step the candidate, then evaluate:
   - ``value1p``: one value-head read on the resulting state;
   - ``rollout``: play out ``rollout_plies`` plies with the agent
     (greedy) on our side and GreedyPlayer(F1, D1) on the opponent's,
     then read the value head at the leaf (terminal states use the
     1 / 0.5 / 0 outcome directly);
   - ``playout``: bracket the state and run ``n_playouts`` native
     ``env.random_rollout`` simulations to terminal, averaging the
     1 / 0.5 / 0 outcome — no value head involved (cheapest per-sample
     signal, but each sample is a full random game).
3. Pick the candidate with the best average; exact ties broken randomly
   via ``self.rng``.

Contract (mirrors ``GreedyPlayer``): ``select_action`` never permanently
mutates the env — every speculative descent is bracketed by
snapshot/restore, and ``log_suspend``/``log_resume`` silence the replay
log during search. Hidden truth (opponent hand refs, dice colors) is
never read for decision-making: the only engine state consulted is
public information (counts, discards, paid/tuned dice, and the decklist
multiset — the union of hand+deck refs, which is public knowledge in
this game; the sampler then re-partitions it randomly).

Value-head semantics (confirmed against value_baseline.py + rl_rollout.py):
the persisted RL head uses signed terminal outcome (1 = win, -1 = loss,
0 = draw) for the acting player. ``_value_me`` converts it to expected
score for search and flips it when the leaf acting player is not
``me``.
"""

from __future__ import annotations

import random
import time

from gicg_env import GicgEnv
from tools.experiments.semantic_training.value_baseline import predict, signed_to_expected_score
from training.core.matchup.greedy_dice import filter_logical_actions
from training.core.matchup.greedy_player import GreedyPlayer
from training.core.matchup.greedy_reroll import reroll_choice
from training.paradigms.az.determinize import (
    PerOpponentPool,
    apply_determinization,
    sample_hidden_state,
)

_MODES = ('value1p', 'rollout', 'playout')


class SearchPlayer:
    """Belief-sampling one-ply search over a semantic-Q value head."""

    def __init__(
        self,
        agent,
        n_beliefs: int = 2,
        mode: str = 'value1p',
        rollout_plies: int = 8,
        n_playouts: int = 4,
        seed: int = 0,
    ):
        if mode not in _MODES:
            raise ValueError(f'mode must be one of {_MODES}, got {mode!r}')
        if n_beliefs < 1:
            raise ValueError(f'n_beliefs must be >= 1, got {n_beliefs}')
        if rollout_plies < 1:
            raise ValueError(f'rollout_plies must be >= 1, got {rollout_plies}')
        if n_playouts < 1:
            raise ValueError(f'n_playouts must be >= 1, got {n_playouts}')
        self.agent = agent
        self.n_beliefs = n_beliefs
        self.mode = mode
        self.rollout_plies = rollout_plies
        self.n_playouts = n_playouts
        self.rng = random.Random(seed)
        # Cumulative search wall time (ms) across select_action calls;
        # evaluate.py accumulates its own per-game wall time when this
        # attribute exists.
        self.last_search_ms = 0.0
        self._pool_spec: PerOpponentPool | None = None
        # Rollout-mode opponent: fixed F1-D1 greedy (matches evaluate.py's
        # default opponent tier) with dice_greedy payment collapse — the
        # same wall-clock speedup evaluate's own opponent uses; per-payment
        # fan-out in rollouts would be pure overhead. Own side plays the
        # wrapped agent greedily.
        self._rollout_opponent = GreedyPlayer(features='F1', depth=1, seed=seed, dice_greedy=True)

    def game_start(self, static_obs) -> None:
        self.agent.game_start(static_obs)
        self._pool_spec = None

    def seed(self, seed: int) -> None:
        self.rng.seed(seed)
        if hasattr(self.agent, 'rng'):
            self.agent.rng.seed(seed ^ 0x51A7)
        self._rollout_opponent.rng.seed(seed ^ 0xD1CE)

    def _ensure_pool_spec(self, env: GicgEnv) -> None:
        """Build the per-opponent card pool spec once per game.

        The pool is the union multiset of hand+deck refs — the public
        decklist. Which refs sit in hand vs deck (the hidden part) is
        never used; sample_hidden_state re-deals that partition at
        random (same construction as loaders._AgentMCTSPlayer)."""
        if self._pool_spec is not None:
            return
        engine = env._engine
        pool_by_player = {p: list(engine.hand_refs(p)) + list(engine.deck_refs(p)) for p in (0, 1)}
        self._pool_spec = PerOpponentPool(pool_by_player)

    @staticmethod
    def _candidates(env: GicgEnv) -> list[int]:
        kinds, _ = env.get_legal_actions()
        try:
            collapsed = filter_logical_actions(env)
        except Exception:
            collapsed = []
        if not collapsed:
            return list(range(len(kinds)))
        return collapsed

    def select_action(self, env: GicgEnv) -> int:
        """Pick the candidate with the best belief-averaged value."""
        start = time.monotonic()
        try:
            return self._search(env)
        finally:
            self.last_search_ms += (time.monotonic() - start) * 1000.0

    def _search(self, env: GicgEnv) -> int:
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            raise RuntimeError('SearchPlayer: env has no legal actions')
        # Pending reroll decisions bypass search entirely (dice-value
        # heuristic, same fast path as GreedyPlayer).
        choice = reroll_choice(env)
        if choice is not None:
            return choice
        candidates = sorted(self._candidates(env))
        if not candidates:
            raise RuntimeError('SearchPlayer: no candidate actions')
        me = env.acting_player
        self._ensure_pool_spec(env)
        env.log_suspend()
        try:
            root = env.snapshot()
            try:
                scored = [(a, self._eval_candidate(env, root, a, me)) for a in candidates]
            finally:
                env.restore(root)
                env.snapshot_free(root)
        finally:
            env.log_resume()
        best = max(s for _, s in scored)
        tied = [a for a, s in scored if s == best]
        return self.rng.choice(tied)

    def _eval_candidate(self, env: GicgEnv, root: int, action: int, me: int) -> float:
        """Average the post-action value over ``n_beliefs`` determinizations."""
        opponent = 1 - me
        env.restore(root)
        opp_dice_total = env.dice_total(opponent)
        total = 0.0
        for _ in range(self.n_beliefs):
            env.restore(root)
            # Speculative clone only: never set a simulation seed on the
            # live root state.
            env.set_simulation_seed(self.rng.getrandbits(63))
            hidden = sample_hidden_state(
                env,
                me,
                self._pool_spec,
                self.rng,
                opponent_dice_total=opp_dice_total,
            )
            apply_determinization(env, hidden, opponent)
            env.step(action)
            if self.mode == 'playout':
                total += self._playout_value(env, me)
            else:
                total += self._leaf_value(env, me)
        return total / self.n_beliefs

    def _playout_value(self, env: GicgEnv, me: int) -> float:
        """Average the terminal outcome over ``n_playouts`` native random
        rollouts from the current (speculative) state."""
        total = 0.0
        for _ in range(self.n_playouts):
            snap = env.snapshot()
            try:
                winner, _ = env.random_rollout(self.rng.getrandbits(63), 512)
                if winner == 2:
                    total += 0.5
                elif winner == me:
                    total += 1.0
            finally:
                env.restore(snap)
                env.snapshot_free(snap)
        return total / self.n_playouts

    def _leaf_value(self, env: GicgEnv, me: int) -> float:
        if env.done:
            return self._outcome(env, me)
        if self.mode == 'value1p':
            return self._value_me(env, me)
        plies = 0
        while plies < self.rollout_plies and not env.done:
            if env.acting_player == me:
                action, _ = self.agent.act_with_logit(env)
                env.step(action)
            else:
                # GreedyPlayer suspends/resumes the replay log itself;
                # temporarily resume ours so its suspend/resume pair
                # stays balanced (nested suspend raises rc=-2).
                env.log_resume()
                try:
                    action = self._rollout_opponent.select_action(env)
                finally:
                    env.log_suspend()
                env.step(action)  # select_action only picks; step here.
            plies += 1
        if env.done:
            return self._outcome(env, me)
        return self._value_me(env, me)

    def _value_me(self, env: GicgEnv, me: int) -> float:
        """Value-head read converted to ``me``'s expected score.

        The head predicts the acting player's signed outcome at the
        observation; convert it and flip when the leaf acting player is the
        opponent."""
        obs = self.agent.observation(env)
        if not obs:
            # Non-terminal state with zero legal actions: engine deadlock
            # guard; treat as a neutral leaf rather than crashing search.
            return 0.5
        _, value = predict(self.agent, obs)
        value = signed_to_expected_score(value)
        return value if env.acting_player == me else 1.0 - value

    @staticmethod
    def _outcome(env: GicgEnv, me: int) -> float:
        if env.winner == 2:
            return 0.5
        return 1.0 if env.winner == me else 0.0
