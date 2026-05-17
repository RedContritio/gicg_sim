"""DMCNetwork — thin nn.Module wrapper around DmcAgent for driver compat.

The unified pipeline driver (``training.core.pipeline``) expects
``make_network`` to return an ``nn.Module``-like object that supports
``.parameters()`` / ``.state_dict()`` / ``.load_state_dict()`` (for
optimizer + ckpt). Our loss path however needs
``DmcAgent.forward_batch(collated_dict)`` because obs is captured by
the agent's private static cache.

FU-W4-DMC-pt2: legacy/ retirement complete. ``DmcAgent`` lives at
adapter top-level (``_agent.py``); ``tools/eval/`` consumes the same
class via the adapter import path.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent


class DMCNetwork(nn.Module):
    """nn.Module wrapper exposing both `forward_batch` (legacy obs path)
    and standard `parameters/state_dict` (driver path).

    Construction owns its own DmcAgent + optimizer; the paradigm passes
    the underlying ``net`` parameters to the driver's external optimizer
    via ``parameters()`` so the driver's ``optimizer.step()`` updates
    the same tensors that ``forward_batch`` reads.
    """

    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu', epsilon: float = 0.0) -> None:
        super().__init__()
        self._agent = DmcAgent(agent_cfg, device=device, lr=1e-4, epsilon=epsilon)
        # Register the underlying ActorCritic as a child module so
        # `self.parameters()` walks them naturally + ckpt round-trip works.
        self.add_module('net', self._agent.net)

    @property
    def agent(self) -> DmcAgent:
        return self._agent

    def forward_batch(self, collated: dict):
        return self._agent.forward_batch(collated)

    def game_start(self, static_obs: Any) -> None:
        self._agent.game_start(static_obs)

    def act_with_logit(self, env: Any):
        return self._agent.act_with_logit(env)

    def select_action(self, env: Any) -> int:
        return self._agent.select_action(env)

    def load_net_only(self, sd: dict) -> None:
        self._agent.load_net_only(sd)

    # nn.Module's state_dict/load_state_dict naturally cover `self.net`
    # because we registered it via add_module.
    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(
            'DMCNetwork.forward not used — call forward_batch(collated) or select_action(env) instead.'
        )
