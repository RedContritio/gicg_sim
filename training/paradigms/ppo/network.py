"""PPONetwork — thin nn.Module wrapper around PPOAgent for driver compat.

The unified pipeline driver (``training.core.pipeline``) expects
``make_network`` to return an ``nn.Module``-like object that supports
``.parameters()`` / ``.state_dict()`` / ``.load_state_dict()`` (for
optimizer + ckpt).

PPO now uses generic structural ActorCritic backbone (via
``make_actor_critic(head_kinds={'policy','value'},
use_typed_damage=True)``) inside ``PPOAgent`` per
``ppo-structural-backbone-migration`` invariant A1. The previous
``_PPOMLPTrunk`` flat MLP backbone (s015-s054 ablation era) is
retired; old ckpts not compatible (D-302 already accepted).

Heads = ('policy', 'value') per P5.1 — exposed for tests + downstream
introspection.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from training.core.network import AgentConfig
from training.paradigms.ppo.agent import PPOAgent


class PPONetwork(nn.Module):
    """nn.Module wrapper exposing PPOAgent + standard module API.

    Construction owns its own PPOAgent (which builds a generic
    ActorCritic with policy + value heads). Driver passes the underlying
    ``net`` parameters to its optimizer via ``parameters()`` so
    ``optimizer.step()`` updates the same tensors ``forward_batch`` reads.

    Spec P5.1: 2 heads (policy + value), shared encoder via generic
    ActorCritic backbone.
    """

    # Spec head names (P5.1) — exposed for tests + downstream introspection.
    heads = ('policy', 'value')

    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu') -> None:
        super().__init__()
        self._agent = PPOAgent(agent_cfg, device=device)
        # Register ActorCritic as child module so module-level
        # parameters() / state_dict() naturally see all its tensors.
        # ``self.net`` is the canonical attribute name (state_dict prefix
        # 'net.*') matching AZ/BC/DMC convention.
        self.add_module('net', self._agent.net)
        self.device = device

    @property
    def agent(self) -> PPOAgent:
        return self._agent

    def forward_batch(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        """Batched structural forward — returns (policy_logits, value).

        Loss path consumes this; rollout path uses self._agent.act(env).
        """
        return self._agent.forward_batch(batch)

    def act(self, env: Any, rng: Any, *, deterministic: bool = False) -> tuple:
        """Single-step rollout actor — returns (action_idx, meta)."""
        return self._agent.act(env, rng, deterministic=deterministic)

    def game_start(self, static_obs: Any) -> None:
        """Per-game cache reset — call once at env reset."""
        self._agent.game_start(static_obs)

    def game_end(self) -> None:
        self._agent.game_end()

    def select_action(self, env: Any) -> int:
        """Player-compatible argmax actor."""
        return self._agent.select_action(env)

    def load_net_only(self, sd: dict) -> None:
        """Load just the ActorCritic weights."""
        self._agent.net.load_state_dict(sd)

    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError(
            'PPONetwork.forward not used — call forward_batch(batch_dict) or act(env, rng) instead.'
        )
