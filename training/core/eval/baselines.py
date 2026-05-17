"""OpponentRegistry — shared by actor mix + eval scenarios.

Spec: design/episode-runner.md §5 (invariant 5).

Same registry used by:
- actor's OpponentPool.sample() → mix random / F1-Dn / historical
- eval scenarios → named baselines F1-D2 / F1-D4 / mcts_pure_200 /
  historical_<tag> (per-ckpt frozen opponent for ladder eval)

Name collisions SHALL raise (per eval-protocol/spec.md). Built-in
factories defer imports to keep core/eval import lightweight."""

from __future__ import annotations

import random
from typing import Any, Callable, Optional


PlayerFactory = Callable[[int, dict], Any]


class OpponentRegistry:
    """Name → PlayerFactory map. ``resolve(spec)`` returns a Player
    instance suitable for env.step dispatch."""

    def __init__(self) -> None:
        self._factories: dict = {}

    def register(self, name: str, factory: PlayerFactory) -> None:
        if name in self._factories:
            raise ValueError(f'OpponentRegistry: name collision {name!r}')
        self._factories[name] = factory

    def names(self) -> list:
        return sorted(self._factories.keys())

    def get(self, name: str, seed: int = 0, params: Optional[dict] = None) -> Any:
        """Build a Player for the given name + seed. Raises if unknown."""
        if name not in self._factories:
            raise ValueError(f'OpponentRegistry: unknown opponent {name!r} (known: {self.names()})')
        return self._factories[name](seed, params or {})


# ---------- Default opponents ---------- #


class _RandomPlayer:
    """Uniform random over legal actions."""

    def __init__(self, seed: int = 0) -> None:
        self.rng = random.Random(seed)

    def select_action(self, env: Any) -> int:
        if hasattr(env, 'get_legal_actions'):
            kinds, _ = env.get_legal_actions()
            n = len(kinds)
        elif hasattr(env, 'legal_mask'):
            n = int(sum(env.legal_mask))
        else:
            return 0
        if n == 0:
            return 0
        return self.rng.randrange(n)


def _make_random(seed: int, params: dict) -> _RandomPlayer:
    return _RandomPlayer(seed=seed)


def _make_greedy(features: str, depth: int, dice_greedy: bool) -> PlayerFactory:
    def factory(seed: int, params: dict) -> Any:
        from training.core.matchup.greedy_player import GreedyPlayer

        return GreedyPlayer(features=features, depth=depth, seed=seed, dice_greedy=dice_greedy)

    return factory


def _make_mcts_pure(n_rollouts: int) -> PlayerFactory:
    def factory(seed: int, params: dict) -> Any:
        from training.core.matchup.players import MCTSPlayer

        return MCTSPlayer(n_rollouts=n_rollouts, seed=seed)

    return factory


def _make_historical(
    ckpt: str,
    paradigm: str,
    n_simulations: int = 0,
    max_rollout_depth: int = 400,
) -> PlayerFactory:
    """Build a factory that loads a frozen-ckpt player on first call.

    Delegates to ``core.matchup.loaders.load_player`` — same code path
    as gauntlet / arena, so behavior matches the canonical eval flow.
    Builder is captured at registration; the agent inside is loaded
    once per registry entry (closure over builder caches load_player).

    Args:
        ckpt: filesystem path to the ckpt blob ({'cfg', 'net'} keys).
        paradigm: paradigm name in core.matchup.loaders.LOADERS (current
            shipped: 'az' / 'cfr'). 'bc' / 'ppo' / 'dmc' SHALL raise via
            LOADERS dispatch — extend LOADERS to add support.
        n_simulations: 0 → argmax via _AZGreedyPlayer; >0 → MCTS-wrapped
            (network prior + value).
        max_rollout_depth: only used when n_simulations > 0.
    """

    def factory(seed: int, params: dict) -> Any:
        from training.core.matchup.loaders import load_player

        spec = {
            'type': paradigm,
            'ckpt': ckpt,
            'n_simulations': n_simulations,
            'max_rollout_depth': max_rollout_depth,
        }
        builder = load_player(spec)
        return builder(seed)

    return factory


def register_default_opponents(reg: OpponentRegistry) -> None:
    """Install random + F1-D{1,2,3,4} + mcts_pure_{50,100,200,400}.

    Historical baselines SHALL be registered explicitly via
    ``register_historical_baseline`` — they are per-ckpt and run-specific,
    not safe defaults.

    Idempotent-by-raise: re-registering raises name collision (callers
    expecting clean reg should construct fresh OpponentRegistry)."""
    reg.register('random', _make_random)
    for d in (1, 2, 3, 4):
        reg.register(f'F1-D{d}', _make_greedy('F1', d, dice_greedy=True))
    for n in (50, 100, 200, 400):
        reg.register(f'mcts_pure_{n}', _make_mcts_pure(n))


def register_historical_baseline(
    reg: OpponentRegistry,
    name: str,
    ckpt: str,
    paradigm: str,
    *,
    n_simulations: int = 0,
    max_rollout_depth: int = 400,
) -> None:
    """Register a frozen-ckpt opponent under a caller-chosen name.

    Convention: name SHALL start with ``'historical_'`` (e.g.
    ``historical_r014_iter_2400``) so scenario sweeps can grep historical
    entries out of ``reg.names()``. The convention is checked here so the
    eval ladder stays auditable.

    Args:
        reg: OpponentRegistry to install into.
        name: registry key. SHALL start with ``'historical_'``.
        ckpt: filesystem path; existence SHALL NOT be pre-checked here
            (lazy — load happens on first ``reg.get(name)`` call so
            registry construction stays cheap).
        paradigm: 'az' / 'cfr' (per core.matchup.loaders.LOADERS).
        n_simulations: 0 = argmax, >0 = MCTS-wrapped.
        max_rollout_depth: forwarded when n_simulations > 0.

    Raises:
        ValueError: if name does not start with 'historical_', or on
            registry name collision.
    """
    if not name.startswith('historical_'):
        raise ValueError(
            f"register_historical_baseline: name {name!r} SHALL start with 'historical_' "
            f'(convention — scenario sweeps grep historical entries by prefix)'
        )
    reg.register(
        name,
        _make_historical(
            ckpt=ckpt,
            paradigm=paradigm,
            n_simulations=n_simulations,
            max_rollout_depth=max_rollout_depth,
        ),
    )
