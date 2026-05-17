"""Player wrappers + loader registry for ``run_matchup``.

Factored out of the original ``training.matchup`` so matchup.py stays
below the line-limit. The dispatch registry (az / random / mcts_pure
/ cfr) lives here; matchup.py imports ``load_player``.
"""

from __future__ import annotations

import random
from typing import Callable, Dict, Protocol

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


class _AZGreedyPlayer:
    """Agent wrapped as pure-argmax (no search). Used for az-type
    players with ``n_simulations == 0``."""

    def __init__(self, agent):
        self.agent = agent

    def select_action(self, env: GicgEnv) -> int:
        self.agent.encode_static(env.static_obs)
        kinds, _ = env.get_legal_actions()
        if len(kinds) == 0:
            raise RuntimeError('AZGreedyPlayer: env has no legal actions')
        refs = env.get_action_refs()
        payments = env.get_legal_action_payments()
        dyn_obs = env._get_obs()
        prior, _v = self.agent.eval_state(dyn_obs, refs, payments)
        return int(np.argmax(prior))


class _AgentMCTSPlayer:
    """Agent wrapped inside MCTS (network prior + value). Used for
    az-type players with ``n_simulations > 0``."""

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


def _load_agent_from_ckpt(ckpt_path: str):
    import torch

    from training.core.network import AgentConfig
    from training.paradigms.az.network import Agent

    blob = torch.load(ckpt_path, weights_only=True, map_location='cpu')
    if not isinstance(blob, dict) or 'cfg' not in blob:
        raise RuntimeError(f"matchup: az ckpt {ckpt_path} missing 'cfg' key")
    # New ckpt schema (core-network-generic-promotion N4):'net_state_dict' key.
    # Legacy 2-key {'net', 'cfg'} no longer supported (Phase 0 removed all
    # pre-redesign ckpts).
    state_key = 'net_state_dict' if 'net_state_dict' in blob else 'net'
    if state_key not in blob:
        raise RuntimeError(
            f"matchup: az ckpt {ckpt_path} missing 'net_state_dict' key "
            f'(post core-network-generic-promotion Phase 0 schema); retrain to new schema.'
        )
    cfg = AgentConfig(**blob['cfg'])
    agent = Agent(cfg)
    agent.net.load_state_dict(blob[state_key])
    agent.net.eval()
    return agent


def _loader_az(spec: dict) -> PlayerBuilder:
    agent = _load_agent_from_ckpt(spec['ckpt'])
    n_sims = int(spec.get('n_simulations', 0))
    max_depth = int(spec.get('max_rollout_depth', 400))

    def builder(seed: int) -> _PlayerProtocol:
        if n_sims == 0:
            return _AZGreedyPlayer(agent)
        return _AgentMCTSPlayer(
            agent,
            n_rollouts=n_sims,
            seed=seed,
            max_rollout_depth=max_depth,
        )

    return builder


def _loader_random(spec: dict) -> PlayerBuilder:
    def builder(seed: int) -> _PlayerProtocol:
        return _RandomPlayer(seed=seed)

    return builder


def _loader_greedy(spec: dict) -> PlayerBuilder:
    """Feature-based greedy evaluation opponent. See
    framework/matchup/greedy_player.py for variant details."""
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


def _loader_cfr(spec: dict) -> PlayerBuilder:
    """Load a CFRStrategyNet ckpt via CFRAgent.

    n_simulations == 0 → argmax over strategy head.
    n_simulations > 0 → MCTS(net prior + value) via the same
    _AgentMCTSPlayer wrapper used for AZ."""
    import torch

    from training.paradigms.cfr.agent import CFRAgent
    from training.paradigms.cfr.strategy_net import CFRNetConfig

    ckpt_path = spec['ckpt']
    blob = torch.load(ckpt_path, weights_only=True, map_location='cpu')
    if not isinstance(blob, dict) or 'cfg' not in blob or 'net' not in blob:
        raise RuntimeError(f"matchup: cfr ckpt {ckpt_path} missing 'cfg' or 'net' key")
    cfg = CFRNetConfig(**blob['cfg'])
    agent = CFRAgent(cfg)
    agent.net.load_state_dict(blob['net'])
    agent.net.eval()

    n_sims = int(spec.get('n_simulations', 0))
    max_depth = int(spec.get('max_rollout_depth', 400))

    def builder(seed: int) -> _PlayerProtocol:
        if n_sims == 0:
            return _AZGreedyPlayer(agent)
        return _AgentMCTSPlayer(
            agent,
            n_rollouts=n_sims,
            seed=seed,
            max_rollout_depth=max_depth,
        )

    return builder


LOADERS: Dict[str, Callable[[dict], PlayerBuilder]] = {
    'az': _loader_az,
    'random': _loader_random,
    'mcts_pure': _loader_mcts_pure,
    'cfr': _loader_cfr,
    'greedy': _loader_greedy,
}


def load_player(spec: dict) -> PlayerBuilder:
    """Dispatch a player spec through LOADERS."""
    if 'type' not in spec:
        raise ValueError(f"player spec missing 'type': {spec}")
    t = spec['type']
    if t not in LOADERS:
        raise ValueError(f'unknown player type: {t!r} (known: {sorted(LOADERS)})')
    return LOADERS[t](spec)
