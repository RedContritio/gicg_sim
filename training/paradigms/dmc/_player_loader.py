"""DMC player loader — registers ``'dmc'`` factory with
``training.core.matchup.loaders`` registry。 Imported by core's lazy
loader on first ``load_player({'type': 'dmc', ...})`` (B4 — close
audit 注释 `core/eval/baselines.py:103-105` "extend LOADERS to add
support" 流毒)。

DMC ckpt schema:CheckpointManager 格式(`training.core.checkpoint.
load_net_state_dict` 已收口 'net.' wrapper strip);eval 端用 raw
ActorCritic + DmcAgent。 n_simulations 字段忽略 — DMC 没 MCTS
prior+value 双头,只能 argmax over Q-head。
"""

from __future__ import annotations

from typing import Any

from gicg_env import GicgEnv
from training.core.checkpoint import load_net_state_dict
from training.core.matchup.loaders import (
    PlayerBuilder,
    _PlayerProtocol,
    register_loader,
)
from training.core.network import AgentConfig


def _load_dmc_agent(ckpt_path: str) -> Any:
    """Load a DmcAgent from a CheckpointManager-format ckpt blob。

    Caller responsibility:`ckpt_path` 是 production DMC training pipeline
    保存的 ckpt(含 `net.` wrapper prefix),helper 自动 strip。
    Network shape 从 `tier`/`make_dmc_default_shape` 默认值取(eval 端不
    保 agent shape 元数据,假设与 production 默认一致;若 mismatch 应在
    `load_state_dict` 报 shape mismatch)。
    """
    from training.core.cfg import make_dmc_default_shape
    from training.paradigms.dmc._agent import DmcAgent

    shape = make_dmc_default_shape()
    agent_cfg = AgentConfig.from_obs_shape(shape)
    agent = DmcAgent(agent_cfg, device='cpu', lr=1e-4, epsilon=0.0)
    state_dict = load_net_state_dict(ckpt_path, map_location='cpu')
    agent.net.load_state_dict(state_dict)
    agent.net.eval()
    return agent


class _DmcArgmaxPlayer:
    """DmcAgent wrapped as gauntlet player。 Calls `game_start` once per
    env reset(`encode_static` hash-cached so repeat calls 走 cache);
    `select_action(env)` delegates to DmcAgent's epsilon=0 argmax path。
    """

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self._last_static_hash: Any = None

    def select_action(self, env: GicgEnv) -> int:
        # game_start 内部 `_hash_static` cache,re-call 同 static_obs 走
        # cache short-circuit;不同 game(reset 后)自动 invalidate。
        static_obs = env.static_obs
        h = id(static_obs)  # cheap pre-check;真 hash 在 game_start 内部
        if h != self._last_static_hash:
            self.agent.game_start(static_obs)
            self._last_static_hash = h
        return self.agent.select_action(env)


def _loader_dmc(spec: dict) -> PlayerBuilder:
    if int(spec.get('n_simulations', 0)) != 0:
        raise NotImplementedError(
            "DMC player loader: n_simulations > 0 unsupported — DMC has no MCTS prior+value "
            'two-head structure。 omit n_simulations or set to 0 (argmax over Q-head)。'
        )
    agent = _load_dmc_agent(spec['ckpt'])

    def builder(seed: int) -> _PlayerProtocol:
        return _DmcArgmaxPlayer(agent)

    return builder


register_loader('dmc', _loader_dmc)
