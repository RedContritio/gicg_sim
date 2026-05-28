"""PPO player loader — registers ``'ppo'`` factory with
``training.core.matchup.loaders`` registry。 Imported by core's lazy
loader on first ``load_player({'type': 'ppo', ...})`` (B4 — close
audit 注释 `core/eval/baselines.py:103-105` "extend LOADERS to add
support" 流毒)。

PPO ckpt schema:CheckpointManager 格式(`training.core.checkpoint.
load_net_state_dict` 已收口 'net.' wrapper strip);eval 端用 raw
ActorCritic + PPOAgent。 n_simulations 字段忽略 — PPO 不是 MCTS
framework,argmax over policy head only(deterministic=True path of
`PPOAgent.act`)。
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


def _load_ppo_agent(ckpt_path: str) -> Any:
    """Load a PPOAgent from a CheckpointManager-format ckpt blob。

    Network shape 从 `make_ppo_default_shape` 默认值取(production
    structural backbone migration 后 PPO shape align with AZ默认)。
    """
    from training.core.cfg import make_ppo_default_shape
    from training.paradigms.ppo.agent import PPOAgent

    shape = make_ppo_default_shape()
    agent_cfg = AgentConfig.from_obs_shape(shape)
    agent = PPOAgent(agent_cfg, device='cpu')
    state_dict = load_net_state_dict(ckpt_path, map_location='cpu')
    agent.net.load_state_dict(state_dict)
    agent.net.eval()
    return agent


class _PpoArgmaxPlayer:
    """PPOAgent wrapped as gauntlet player。 `deterministic=True` mode
    of `PPOAgent.act` — argmax over policy logits, no stochastic
    sampling。"""

    def __init__(self, agent: Any, seed: int = 0) -> None:
        self.agent = agent
        self.rng = random.Random(seed)
        self._game_started = False

    def select_action(self, env: GicgEnv) -> int:
        if not self._game_started:
            self.agent.game_start(env.static_obs)
            self._game_started = True
        # PPOAgent.act 返 (action_idx, meta);deterministic=True 是 argmax。
        action_idx, _meta = self.agent.act(env, self.rng, deterministic=True)
        return int(action_idx)


def _loader_ppo(spec: dict) -> PlayerBuilder:
    if int(spec.get('n_simulations', 0)) != 0:
        raise NotImplementedError(
            "PPO player loader: n_simulations > 0 unsupported — PPO is not an MCTS "
            'framework。 omit n_simulations or set to 0 (deterministic argmax over policy)。'
        )
    agent = _load_ppo_agent(spec['ckpt'])

    def builder(seed: int) -> _PlayerProtocol:
        return _PpoArgmaxPlayer(agent, seed=seed)

    return builder


register_loader('ppo', _loader_ppo)
