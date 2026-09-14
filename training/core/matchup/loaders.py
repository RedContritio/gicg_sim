"""Player wrappers and lazy loader registry for ``run_matchup``.

- core provides ``register_loader(name, factory)`` API + ``LOADERS``
  as a read-only view of a private registry;
- universal loaders (``random``, ``greedy``, and ``mcts_pure``) register
  at module import without importing a training paradigm;
- paradigm-specific loaders live in
  ``training/paradigms/<name>/_player_loader.py`` and call
  ``register_loader`` when imported;
- ``load_player(spec)`` lazy-imports the paradigm's loader module on
  demand. Membership checks and iteration also trigger lazy imports for
  known paradigm names.

``_AgentMCTSPlayer`` is a shared wrapper, but its search implementation
currently comes from ``training.paradigms.az.mcts`` at call time.
"""

from __future__ import annotations

import importlib
import random
from typing import Callable, Dict, Mapping, Protocol

import numpy as np

from gicg_env import GicgEnv
from training.core.matchup.players import MCTSPlayer


class _PlayerProtocol(Protocol):
    def select_action(self, env: GicgEnv) -> int: ...


class _RandomPlayer:
    """Uniform-random over the current legal action list."""

    def __init__(self, seed: int = 0):
        self.rng = random.Random(seed)

    def select_action(self, env: GicgEnv) -> int:
        kinds, _ = env.get_legal_actions()
        n = len(kinds)
        if n == 0:
            raise RuntimeError('RandomPlayer: env has no legal actions')
        return self.rng.randrange(n)


class _AgentArgmaxPlayer:
    """Agent wrapped as pure-argmax (no search). Used for ckpt-bearing
    players with ``n_simulations == 0`` — works for any agent with a
    ``.encode_static(static_obs)`` + ``.eval_state(dyn_obs, refs, payments)``
    interface (AZ Agent / CFRAgent both qualify)."""

    def __init__(self, agent):
        self.agent = agent

    def select_action(self, env: GicgEnv) -> int:
        self.agent.encode_static(env.static_obs)
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            raise RuntimeError('AgentArgmaxPlayer: env has no legal actions')
        refs = env.get_action_refs()
        payments = env.get_legal_action_payments()
        dyn_obs = env._get_obs()
        prior, _v = self.agent.eval_state(dyn_obs, refs, payments)
        return int(np.argmax(prior))


# Backward-compat alias (older test imports).
_AZGreedyPlayer = _AgentArgmaxPlayer


class _AgentMCTSPlayer:
    """Agent wrapped inside MCTS (network prior + value). Used by
    paradigm loaders with ``n_simulations > 0``。

    The wrapper is paradigm-agnostic to callers, while the MCTS
    implementation is imported from ``paradigms.az.mcts`` at call time."""

    def __init__(self, agent, n_rollouts: int, seed: int = 0, max_rollout_depth: int = 400):
        from training.paradigms.az.mcts import MCTSConfig

        self.agent = agent
        self.rng = random.Random(seed)
        self.config = MCTSConfig(
            n_rollouts=n_rollouts,
            max_rollout_depth=max_rollout_depth,
            parallel_rollouts=1,
            dirichlet_eps=0.0,
            temperature_switch_step=0,
            value_mix_lambda=1.0,
            prior_mix_lambda=1.0,
            lambda_anneal_games=0,
            profile=False,
            discovery_checkpoints=(),
        )

    def select_action(self, env: GicgEnv) -> int:
        from training.paradigms.az.determinize import PerOpponentPool
        from training.paradigms.az.mcts import mcts_search

        self.agent.encode_static(env.static_obs)
        engine = env._engine
        pool_by_player = {p: list(engine.hand_refs(p)) + list(engine.deck_refs(p)) for p in (0, 1)}
        pool_spec = PerOpponentPool(pool_by_player)

        env.log_suspend()
        try:
            chosen, _info = mcts_search(
                env,
                self.agent,
                pool_spec,
                self.rng,
                viewing_player=env.acting_player,
                config=self.config,
                game_step=0,
            )
        finally:
            env.log_resume()
        return chosen


PlayerBuilder = Callable[[int], _PlayerProtocol]
LoaderFactory = Callable[[dict], PlayerBuilder]


# -----------------------------------------------------------------------------
# Registry
# -----------------------------------------------------------------------------

_REGISTRY: Dict[str, LoaderFactory] = {}

# Paradigm names whose loader lives under
# ``training.paradigms.<name>._player_loader`` and self-registers at
# module load. The BC name is registered as well, but its loader raises
# ``NotImplementedError`` because no BC gauntlet adapter exists.
_PARADIGM_LOADER_NAMES = ('az', 'bc', 'cfr', 'dmc', 'ppo')


def register_loader(name: str, factory: LoaderFactory) -> None:
    """Register a player-loader factory under ``name``. Paradigm
    self-registration calls this from their ``_player_loader`` module.

    Re-registration with the same name overwrites the previous factory
    silently (loader modules may be imported more than once during
    repeated test fixtures); fail-loud on name collisions would force
    tests to teardown explicitly without much safety benefit.
    """
    _REGISTRY[name] = factory


def _try_lazy_load(name: str) -> None:
    """If ``name`` is a known paradigm and not yet registered, import
    the paradigm's ``_player_loader`` module to trigger self-registration."""
    if name in _REGISTRY:
        return
    if name not in _PARADIGM_LOADER_NAMES:
        return
    try:
        importlib.import_module(f'training.paradigms.{name}._player_loader')
    except ImportError:
        pass


def _lazy_load_all() -> None:
    """Eagerly trigger lazy-load for all known paradigm loaders.
    Used by enumeration paths (iter / len / keys) so callers see the
    full set."""
    for name in _PARADIGM_LOADER_NAMES:
        _try_lazy_load(name)


class _LazyLoaderRegistry(Mapping):
    """Read-only mapping over ``_REGISTRY`` with lazy paradigm import
    on miss. Callers can query entries without importing paradigm modules
    explicitly."""

    def __getitem__(self, name: str) -> LoaderFactory:
        _try_lazy_load(name)
        return _REGISTRY[name]

    def __contains__(self, name: object) -> bool:
        if not isinstance(name, str):
            return False
        _try_lazy_load(name)
        return name in _REGISTRY

    def __iter__(self):
        _lazy_load_all()
        return iter(_REGISTRY)

    def __len__(self) -> int:
        _lazy_load_all()
        return len(_REGISTRY)


LOADERS: Mapping[str, LoaderFactory] = _LazyLoaderRegistry()


# -----------------------------------------------------------------------------
# Builtin universal loaders (no paradigm import).
# -----------------------------------------------------------------------------


def _loader_random(spec: dict) -> PlayerBuilder:
    def builder(seed: int) -> _PlayerProtocol:
        return _RandomPlayer(seed=seed)

    return builder


def _loader_greedy(spec: dict) -> PlayerBuilder:
    """Feature-based greedy evaluation opponent. See
    training/core/matchup/greedy_player.py for variant details."""
    from training.core.matchup.greedy_player import GreedyPlayer

    features = str(spec.get('features', 'F1'))
    depth = int(spec.get('depth', 1))
    dice_greedy = bool(spec.get('dice_greedy', False))

    def builder(seed: int) -> _PlayerProtocol:
        return GreedyPlayer(features=features, depth=depth, seed=seed, dice_greedy=dice_greedy)

    return builder


def _loader_mcts_pure(spec: dict) -> PlayerBuilder:
    n_sims = int(spec.get('n_simulations', 0))
    if n_sims <= 0:
        raise ValueError('mcts_pure requires n_simulations > 0 (no network prior to fall back on at budget=0)')

    def builder(seed: int) -> _PlayerProtocol:
        return MCTSPlayer(n_rollouts=n_sims, seed=seed)

    return builder


register_loader('random', _loader_random)
register_loader('greedy', _loader_greedy)
register_loader('mcts_pure', _loader_mcts_pure)


# -----------------------------------------------------------------------------
# Dispatch
# -----------------------------------------------------------------------------


def load_player(spec: dict) -> PlayerBuilder:
    """Dispatch a player spec through the loader registry. Triggers
    lazy paradigm import on miss for known paradigm names."""
    if 'type' not in spec:
        raise ValueError(f"player spec missing 'type': {spec}")
    t = spec['type']
    _try_lazy_load(t)
    if t not in _REGISTRY:
        # Enumerate the full set for the error message — pull in any
        # not-yet-loaded paradigm loaders so the user sees all options.
        _lazy_load_all()
        raise ValueError(f'unknown player type: {t!r} (known: {sorted(_REGISTRY)})')
    return _REGISTRY[t](spec)
