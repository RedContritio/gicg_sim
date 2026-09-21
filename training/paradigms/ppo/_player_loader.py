"""Register the PPO checkpoint player loader.

Checkpoints use the ``CheckpointManager`` schema and are loaded through
``load_net_state_dict``. PPO has no MCTS interface, so the loader accepts
only ``n_simulations == 0`` and uses deterministic policy selection.
"""

from __future__ import annotations

import random
from typing import Any

from gicg_env import GicgEnv
from training.core.checkpoint import load_net_state_dict
from training.core.matchup.loaders import (
    PlayerBuilder,
    _PlayerProtocol,
    register_loader,
)
from training.core.network import AgentConfig


def _load_ppo_agent(ckpt_path: str, *, verify_provenance: bool = True) -> Any:
    """Load a PPOAgent using the default production observation shape."""
    from training.core.cfg import make_ppo_default_shape
    from training.paradigms.ppo.agent import PPOAgent

    shape = make_ppo_default_shape()
    agent_cfg = AgentConfig.from_obs_shape(shape)
    agent = PPOAgent(agent_cfg, device='cpu')
    state_dict = load_net_state_dict(
        ckpt_path,
        map_location='cpu',
        verify_provenance=verify_provenance,
    )
    agent.net.load_state_dict(state_dict)
    agent.net.eval()
    return agent


class _PpoArgmaxPlayer:
    """Wrap ``PPOAgent`` as a deterministic gauntlet player."""

    def __init__(self, agent: Any, seed: int = 0) -> None:
        self.agent = agent
        self.rng = random.Random(seed)
        self._env = None

    def select_action(self, env: GicgEnv) -> int:
        if self._env is not env:
            self.agent.game_start(env.static_obs)
            self._env = env
        # ``deterministic=True`` selects the maximum policy logit.
        action_idx, _meta = self.agent.act(env, self.rng, deterministic=True)
        return int(action_idx)


def _loader_ppo(spec: dict) -> PlayerBuilder:
    if int(spec.get('n_simulations', 0)) != 0:
        raise NotImplementedError(
            'PPO player loader does not support n_simulations > 0; '
            'omit it or set it to 0 for deterministic policy selection.'
        )
    agent = _load_ppo_agent(
        spec['ckpt'],
        verify_provenance=not bool(spec.get('allow_unverified_checkpoint', False)),
    )

    def builder(seed: int) -> _PlayerProtocol:
        return _PpoArgmaxPlayer(agent, seed=seed)

    return builder


register_loader('ppo', _loader_ppo)
