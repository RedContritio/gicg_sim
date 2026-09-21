"""AZ fixed-opponent pool — ExIt remediation for the A5.2 mirror lock.

Mirror selfplay (both seats share the training network) historically
locked into mirror Nash plateaus and drifted (docs/5_history: 2026-04-28
AZ shutdown; r010-012 BC warm-start destroyed by mirror-opponent
distribution drift). The ExIt prescription
(docs/3_plans/cards/exit_az.md): the opponent seat is driven by a FIXED
pool player — feature-greedy 为主 + optional random / historical ckpt
ring — sampled per episode, while only the agent seat runs MCTS and
feeds the replay buffer.

Semantics mirror DMC's ``OpponentPool`` (``training/paradigms/dmc/
_opponent.py``): per-episode ``sample()`` → player with
``select_action(env) -> int``; historical is a ring buffer of learner
ckpt snapshots with cold-start fallback to random. DMC's pool hardcodes
F1-D2/F1-D4, but AZ needs a configurable depth (CPU pilot smoke runs
F1-D1), so this is a thin AZ-side sibling. ``RandomPlayer`` is
duplicated rather than imported across paradigms (intentional dup —
paradigm isolation per ADR-0006, same rationale as ``derive_seed`` in
``training/paradigms/az/collector.py``); GreedyPlayer comes from
``training.core.matchup`` (core, shared).
"""

from __future__ import annotations

import random
from collections import deque
from typing import Any, Callable, Optional

from training.core.matchup.greedy_player import GreedyPlayer
from training.paradigms.az.config import FixedOpponentCfg

# A "player" is anything with select_action(env) -> int (DMC parity).
AgentFactory = Callable[[dict], Any]


def make_snapshot_factory(
    agent_cfg: Any,
    device: str,
    mcts_cfg: Any,
    card_pool_spec: Any,
    seed: int = 0,
) -> AgentFactory:
    """Build an AgentFactory for the historical ring: snapshot state_dict
    (pipeline weight-broadcast format — AZNetwork keys, inner net under
    the ``net.`` prefix) → AZSnapshotPlayer. Shared by the serial
    make_opponent_pool and the async actor-side pool (each actor builds
    its own players locally; no player crosses a process boundary)."""

    def historical_factory(state_dict: dict) -> Any:
        from training.paradigms.az.network import Agent

        inner = {k[len('net.') :]: v for k, v in state_dict.items() if k.startswith('net.')}
        if not inner:
            raise ValueError(
                f'fixed_opponent historical snapshot: no `net.` keys found (got {sorted(state_dict)[:5]}...)'
            )
        agent = Agent(agent_cfg, device=device)
        agent.net.load_state_dict(inner)
        agent.net.eval()
        return AZSnapshotPlayer(agent, mcts_cfg, card_pool_spec, seed=seed)

    return historical_factory


class RandomPlayer:
    """Uniform random over legal actions; ``select_action(env) -> int``.

    Intentional dup of ``training.paradigms.dmc._opponent.RandomPlayer``
    — paradigm isolation per ADR-0006 (see module docstring)."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def select_action(self, env) -> int:
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            return 0
        return self.rng.randrange(len(kinds))


class AZSnapshotPlayer:
    """MCTS player over a historical AZ ckpt snapshot (ring entry).

    Satisfies the ``select_action(env) -> int`` opponent contract: runs
    ``mcts_search`` with the snapshot net as the leaf evaluator. The
    Agent static-obs cache lifecycle is bracketed per call
    (``game_start``/``game_end``) — the same contract
    ``play_self_game`` holds around a whole mirror game.
    """

    def __init__(
        self,
        agent: Any,
        mcts_cfg: Any,
        card_pool_spec: Any,
        seed: int = 0,
    ):
        self._agent = agent
        self._mcts_cfg = mcts_cfg
        self._card_pool_spec = card_pool_spec
        self._rng = random.Random(seed)
        self._decision_seq = 0

    def select_action(self, env) -> int:
        from training.paradigms.az.mcts import mcts_search

        self._agent.game_start(env.static_obs)
        try:
            chosen, _ = mcts_search(
                env,
                self._agent,
                self._card_pool_spec,
                self._rng,
                viewing_player=env.acting_player,
                config=self._mcts_cfg,
                game_step=self._decision_seq,
            )
        finally:
            self._agent.game_end()
        self._decision_seq += 1
        return int(chosen)


class FixedOpponentPool:
    """Fixed-opponent sampler for AZ non-mirror selfplay.

    Per episode the collector calls ``sample()`` → a fresh player
    instance. Kinds (weighted by ``FixedOpponentCfg``):

    - ``random``: uniform over legal actions
    - ``greedy``: ``GreedyPlayer(features/depth/dice_greedy)`` from cfg
    - ``historical``: ckpt ring via ``agent_factory``; cold-start
      (empty ring or no factory) falls back to random and reports that
      effective kind in ``last_kind``.
    """

    def __init__(
        self,
        cfg: FixedOpponentCfg,
        agent_factory: Optional[AgentFactory] = None,
        mcts_cfg: Any = None,
        card_pool_spec: Any = None,
        seed: Optional[int] = None,
    ):
        self.cfg = cfg
        self._agent_factory = agent_factory
        self._mcts_cfg = mcts_cfg
        self._card_pool_spec = card_pool_spec
        self._ring: deque = deque(maxlen=cfg.ring_size)
        self._rng = random.Random(cfg.seed if seed is None else seed)
        self.last_kind: Optional[str] = None

    def seed(self, seed: int) -> None:
        self._rng.seed(seed)

    def state_dict(self) -> dict:
        return {'ring': list(self._ring), 'ring_size': self.cfg.ring_size, 'rng': self._rng.getstate()}

    def load_state_dict(self, state: dict) -> None:
        if state['ring_size'] != self.cfg.ring_size or len(state['ring']) > self.cfg.ring_size:
            raise ValueError('historical opponent ring capacity mismatch')
        self._ring = deque(state['ring'], maxlen=self.cfg.ring_size)
        self._rng.setstate(state['rng'])

    def add_snapshot(self, state_dict: dict) -> None:
        """Add a learner ckpt snapshot to the historical ring."""
        self._ring.append(state_dict)

    def snapshots(self) -> list:
        """Current ring contents (parent-side read for the broadcast)."""
        return list(self._ring)

    def load_snapshots(self, snapshots: list) -> None:
        """Replace the historical ring contents — actor-side refresh from
        the weight-broadcast channel. Excess-older entries drop."""
        self._ring = deque(list(snapshots)[-self.cfg.ring_size :], maxlen=self.cfg.ring_size)

    def sample(self):
        """Return a player instance for one episode."""
        kind = self._weighted_choice()
        if kind == 'historical' and (not self._ring or self._agent_factory is None):
            kind = 'random'
        self.last_kind = kind
        return self._build_player(kind)

    def _weighted_choice(self) -> str:
        weights = (self.cfg.random, self.cfg.greedy, self.cfg.historical)
        kinds = ('random', 'greedy', 'historical')
        return self._rng.choices(kinds, weights=weights, k=1)[0]

    def _build_player(self, kind: str):
        if kind == 'random':
            return RandomPlayer(seed=self._rng.randint(0, 2**31 - 1))
        if kind == 'greedy':
            return GreedyPlayer(
                features=self.cfg.features,
                depth=self.cfg.depth,
                dice_greedy=self.cfg.dice_greedy,
                seed=self._rng.randint(0, 2**31 - 1),
            )
        if kind == 'historical':
            state_dict = self._rng.choice(self._ring)
            return self._agent_factory(state_dict)
        raise ValueError(f'unknown opponent kind: {kind}')
