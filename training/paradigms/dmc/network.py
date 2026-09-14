"""Driver-compatible ``nn.Module`` wrapper around ``DmcAgent``.

The shared ``AgentModuleWrapper`` supplies the standard forwarding, game
lifecycle, selection, and state-dict surface. This subclass adds the DMC
constructor and ``act_with_logit`` rollout hook.
"""

from __future__ import annotations

from typing import Any

from training.core.network import AgentConfig, AgentModuleWrapper
from training.paradigms.dmc._agent import DmcAgent


class DMCNetwork(AgentModuleWrapper):
    """Expose ``DmcAgent`` through the shared driver-compatible module API."""

    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu', epsilon: float = 0.0) -> None:
        agent = DmcAgent(agent_cfg, device=device, lr=1e-4, epsilon=epsilon)
        super().__init__(agent)

    def act_with_logit(self, env: Any):
        """Return ``(action_idx, logit)`` for DMC rollout recording."""
        return self._agent.act_with_logit(env)
