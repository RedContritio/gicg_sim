"""AgentModuleWrapper — generic nn.Module wrapper around AgentBase。

W2-6 (post-2026-05-28):pre-W2 DMCNetwork / PPONetwork / BCNetwork 三份
near-identical thin wrapper(audit finding 中优 #9 / #6),都做同一件事:

  class XNetwork(nn.Module):
      def __init__(self, agent_cfg, device, ...):
          super().__init__()
          self._agent = XAgent(agent_cfg, device, ...)
          self.add_module('net', self._agent.net)
      @property def agent(self): return self._agent
      def forward_batch(self, batch): return self._agent.forward_batch(batch)
      def game_start(self, static_obs): return self._agent.game_start(static_obs)
      def select_action(self, env): return self._agent.select_action(env)
      def load_net_only(self, sd): return self._agent.load_net_only(sd)
      def forward(self, *a, **k): raise NotImplementedError(...)

This base captures the common skeleton。 DMC + PPO 继承本类只 override
paradigm-specific extras(DMC: act_with_logit / epsilon ctor;PPO: heads class
attr / act / game_end)。 BC + AZ + CFR 暂留 own 子类 — BC 直接包 ActorCritic
不持 Agent 对象;AZ 有 BASIC_HEAD_CLASSES + load_net_only delegate to agent;
CFR 完全异构(2 head:avg_policy + advantage)。

driver 端约定不变:`Paradigm.make_network()` 返 nn.Module 子类,driver 调用
`.parameters()` / `.state_dict()` / `.load_state_dict()` / `.train()` / `.eval()`,
以及 paradigm-specific `forward_batch` / `select_action` 等 — 全部由本基类提供。
"""

from __future__ import annotations

from typing import Any

import torch.nn as nn


class AgentModuleWrapper(nn.Module):
    """Generic nn.Module wrapper around an AgentBase subclass。

    Subclass usage(DMC example):

        class DMCNetwork(AgentModuleWrapper):
            def __init__(self, agent_cfg, device='cpu', epsilon=0.0):
                agent = DmcAgent(agent_cfg, device=device, lr=1e-4, epsilon=epsilon)
                super().__init__(agent)
            # 继承 forward_batch / game_start / select_action / load_net_only / forward
            # Optional override:
            def act_with_logit(self, env):
                return self._agent.act_with_logit(env)
    """

    def __init__(self, agent: Any) -> None:
        super().__init__()
        self._agent = agent
        # Register inner net as child module so .parameters() / .state_dict()
        # walks the agent's tensors naturally。
        if not hasattr(agent, 'net'):
            raise TypeError(
                f'AgentModuleWrapper: agent ({type(agent).__name__}) must expose .net '
                f'(the nn.Module to register as wrapper child for parameters/state_dict).'
            )
        self.add_module('net', agent.net)

    @property
    def agent(self) -> Any:
        return self._agent

    def forward_batch(self, batch: dict) -> Any:
        return self._agent.forward_batch(batch)

    def game_start(self, static_obs: Any) -> Any:
        return self._agent.game_start(static_obs)

    def game_end(self) -> Any:
        if hasattr(self._agent, 'game_end'):
            return self._agent.game_end()
        return None

    def select_action(self, env: Any) -> int:
        return self._agent.select_action(env)

    def load_net_only(self, sd: dict) -> None:
        if hasattr(self._agent, 'load_net_only'):
            self._agent.load_net_only(sd)
        else:
            self._agent.net.load_state_dict(sd)

    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(
            f'{type(self).__name__}.forward not used — call forward_batch(batch) or '
            f'select_action(env) instead.'
        )
