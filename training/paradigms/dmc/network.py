"""DMCNetwork — thin nn.Module wrapper around DmcAgent for driver compat.

W2-6 (post-2026-05-28):pre-W2 DMCNetwork 是 67 行的 paradigm-local 重复
boilerplate (audit finding 中优 #9 — 与 PPONetwork 平行 88 行近字模重复);
post-W2-6 继承 ``training.core.network.AgentModuleWrapper`` 把通用 dispatch
(forward_batch / game_start / select_action / load_net_only / forward 抛
NotImplementedError)上提到 core,本类仅声明:
- DMC-specific ctor (epsilon 参数,默认 0.0;internal DmcAgent 持 1e-4 lr)
- DMC-specific extra ``act_with_logit(env)``(rollout 路径 hook,不在通用
  AgentModuleWrapper 集合)

FU-W4-DMC-pt2: legacy/ retirement complete. ``DmcAgent`` lives at adapter
top-level (``_agent.py``); ``tools/eval/`` consumes the same class via the
adapter import path.
"""

from __future__ import annotations

from typing import Any

from training.core.network import AgentConfig, AgentModuleWrapper
from training.paradigms.dmc._agent import DmcAgent


class DMCNetwork(AgentModuleWrapper):
    """nn.Module wrapper exposing DmcAgent + driver-compatible
    parameters/state_dict surface。 base 提供 forward_batch /
    game_start / game_end / select_action / load_net_only / forward。"""

    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu', epsilon: float = 0.0) -> None:
        agent = DmcAgent(agent_cfg, device=device, lr=1e-4, epsilon=epsilon)
        super().__init__(agent)

    def act_with_logit(self, env: Any):
        """DMC-specific:rollout 路径返回 (action_idx, logit) tuple,
        InfServer-side 写 transition record 时记 logit 供 retrace IS
        weighting。 不属于通用 AgentModuleWrapper 集合(其它 paradigm 没此
        api)。"""
        return self._agent.act_with_logit(env)
