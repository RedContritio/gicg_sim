"""Generic ``nn.Module`` wrapper around an ``AgentBase`` instance.

The wrapper registers the agent's network as its ``net`` child and
forwards the common training, lifecycle, action-selection, and net-only
loading methods. Paradigm wrappers can add their own methods as needed.
"""

from __future__ import annotations

from typing import Any

import torch.nn as nn


class AgentModuleWrapper(nn.Module):
    """Generic ``nn.Module`` wrapper around an ``AgentBase`` subclass.

    Subclass usage(DMC example):

        class DMCNetwork(AgentModuleWrapper):
            def __init__(self, agent_cfg, device='cpu', epsilon=0.0):
                agent = DmcAgent(agent_cfg, device=device, lr=1e-4, epsilon=epsilon)
                super().__init__(agent)
            # Inherits the common delegation methods.
            # Optional override:
            def act_with_logit(self, env):
                return self._agent.act_with_logit(env)
    """

    def __init__(self, agent: Any) -> None:
        super().__init__()
        self._agent = agent
        # Register inner net as child module so .parameters() / .state_dict()
        # walks the agent's tensors naturally.
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
            f'{type(self).__name__}.forward not used — call forward_batch(batch) or select_action(env) instead.'
        )
