"""PPONetwork — thin nn.Module wrapper around PPOAgent for driver compat.

W2-6 (post-2026-05-28):pre-W2 PPONetwork 是 88 行 paradigm-local 重复
boilerplate (audit finding 中优 #9 — 与 DMCNetwork 平行 67 行近字模重复);
post-W2-6 继承 ``training.core.network.AgentModuleWrapper`` 把通用 dispatch
(forward_batch / game_start / game_end / select_action / load_net_only /
forward 抛 NotImplementedError)上提到 core,本类仅声明:
- ``heads`` class attr(P5.1 — exposed for tests + downstream introspection)
- PPO-specific extra ``act(env, rng, *, deterministic=False)``(rollout
  actor — 不属于通用 AgentModuleWrapper 集合,signature 含 rng + deterministic)

PPO now uses generic structural ActorCritic backbone (via
``make_actor_critic(head_kinds={'policy','value'}, use_typed_damage=True)``)
inside ``PPOAgent`` per ``ppo-structural-backbone-migration`` invariant A1.
The previous ``_PPOMLPTrunk`` flat MLP backbone (s015-s054 ablation era) is
retired; old ckpts not compatible (D-302 already accepted).

Heads = ('policy', 'value') per P5.1 — exposed for tests + downstream
introspection.
"""

from __future__ import annotations

from typing import Any

import torch

from training.core.network import AgentConfig, AgentModuleWrapper
from training.paradigms.ppo.agent import PPOAgent


class PPONetwork(AgentModuleWrapper):
    """nn.Module wrapper exposing PPOAgent + driver-compatible
    parameters/state_dict surface。 base 提供 forward_batch /
    game_start / game_end / select_action / load_net_only / forward。
    Spec P5.1: 2 heads (policy + value), shared encoder via generic
    ActorCritic backbone。"""

    # Spec head names (P5.1) — exposed for tests + downstream introspection.
    heads = ('policy', 'value')

    def __init__(self, agent_cfg: AgentConfig, device: str = 'cpu') -> None:
        agent = PPOAgent(agent_cfg, device=device)
        super().__init__(agent)
        self.device = device

    def forward_batch(self, batch: dict) -> tuple[torch.Tensor, torch.Tensor]:
        """Batched structural forward — returns (policy_logits, value)。
        Loss path consumes this;rollout path uses self._agent.act(env)。"""
        return self._agent.forward_batch(batch)

    def act(self, env: Any, rng: Any, *, deterministic: bool = False) -> tuple:
        """Single-step rollout actor — returns (action_idx, meta)。
        Not part of the generic AgentModuleWrapper surface (signature
        diverges from other paradigms with the rng + deterministic args)。"""
        return self._agent.act(env, rng, deterministic=deterministic)
