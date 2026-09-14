"""AZEpisodePolicy — MCTS-driven act + z_target finalize.

Implements core.protocols.EpisodePolicy for the AZ paradigm. Spec
A1.1-A1.3: every action is decided by IS-MCTS rollout (no random
sampling at the actor side except for Dirichlet noise inside the
search). The policy delegates to ``training.paradigms.az.mcts.mcts_search``,
forwarding the provider's ``forward`` to the search as a leaf
``evaluator.eval_state``.

Note: P4 serial-mode AZ does NOT route episode play through
``training.core.actor.EpisodeRunner`` because GICG's static-observation cache
 and MCTS root rebuilding live inside ``training.paradigms.az.selfplay``. The
collector calls ``play_self_game`` directly. This policy class exists
for protocol conformance + tests + future async-mode wiring.
"""

from __future__ import annotations

import random
from typing import Any

import numpy as np


class AZEpisodePolicy:
    """MCTS-driven actor policy. Stateless across episodes; an action
    picker that delegates to ``mcts_search``."""

    # Schema tag for downstream Buffer compat checks.
    transition_schema = 'az_transition'

    def __init__(
        self,
        mcts_cfg: Any = None,
        card_pool_spec: Any = None,
        seed: int = 0,
        deterministic: bool = False,
        n_counter_slots: int = 0,
        max_actions: int = 0,
    ) -> None:
        self.mcts_cfg = mcts_cfg
        self.card_pool_spec = card_pool_spec
        self.deterministic = bool(deterministic)
        self.rng = random.Random(seed)
        self.n_counter_slots = int(n_counter_slots)
        self.max_actions = int(max_actions)

    def reset(self) -> None:
        """No per-episode state in the policy itself; the MCTS tree is
        rebuilt at each call. RNG intentionally persistent so the
        Dirichlet noise diverges across actions within a run."""
        return None

    def act(self, obs: Any, mask: Any, provider: Any) -> tuple:
        """Decide one action via IS-MCTS.

        Spec A1.2: every leaf expansion calls ``provider.forward``. We
        hand the provider into ``mcts_search`` as the ``evaluator`` —
        any object exposing ``eval_state(dyn, refs, payments)`` works,
        which AZNetwork / InferenceClient both do.

        Note: AZ MCTS requires the calling env (not just obs) because
        of tree determinization + perfect-replay; so the protocol-level
        ``(obs, mask)`` signature is satisfied by carrying env in
        ``obs['env']`` when called via the protocol path. The legacy
        ``play_self_game`` collector path bypasses this and calls
        mcts_search directly.
        """
        env = obs.get('env') if isinstance(obs, dict) else None
        viewing_player = obs.get('viewing_player', 0) if isinstance(obs, dict) else 0
        game_step = obs.get('game_step', 0) if isinstance(obs, dict) else 0
        if env is None:
            raise ValueError(
                'AZEpisodePolicy.act: obs must carry env (key "env") for MCTS search; '
                'protocol-level act path is used by async collection. '
                'Serial-mode AZ collects via training.paradigms.az.selfplay.play_self_game directly.'
            )
        if self.mcts_cfg is None:
            raise ValueError('AZEpisodePolicy.act: mcts_cfg missing — call from factory that wires it')
        if self.card_pool_spec is None:
            raise ValueError('AZEpisodePolicy.act: card_pool_spec missing — needed for determinization')

        from training.paradigms.az.mcts import mcts_search

        chosen, info = mcts_search(
            env,
            provider,
            self.card_pool_spec,
            self.rng,
            viewing_player=viewing_player,
            config=self.mcts_cfg,
            game_step=game_step,
        )
        meta = {
            'pi': info['pi'],
            'discovery': bool(info.get('discovery_events', False)),
            'n_legal': int(len(info['pi'])),
        }
        return int(chosen), meta

    def finalize_episode(self, transitions: list, winner: int, acting_player: int = 0) -> list:
        """Backfill z_target on each recorded transition (A1.3 —
        terminal reward, no bootstrap).

        Args:
            transitions: list of dicts (the per-step entries from
                ``training.paradigms.az.selfplay``).
            winner: env winner id (0 / 1 / -1 / 2).
            acting_player: acting player id at the step (per-step in
                transitions; this default applies to all steps if not
                set per entry).
        """
        if winner < 0 or winner == 2:
            z_p0 = 0.0
        elif winner == 0:
            z_p0 = 1.0
        elif winner == 1:
            z_p0 = -1.0
        else:
            raise ValueError(f'AZEpisodePolicy.finalize_episode: unknown winner={winner}')
        out: list = []
        for t in transitions:
            if not isinstance(t, dict):
                raise TypeError(f'AZEpisodePolicy.finalize_episode: transition must be dict, got {type(t).__name__}')
            rec = dict(t)
            acting = rec.pop('_acting_player', acting_player)
            rec['z_target'] = float(z_p0 if acting == 0 else -z_p0)
            out.append(rec)
        return out
