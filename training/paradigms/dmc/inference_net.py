"""DMCInferenceNet — tensor-shaped wrapper around ActorCritic for DMC.

DmcAgent's act_with_logit takes ``env`` and runs inference via internal
state (cached hook_emb, structural fields). That couples inference to
the agent's stateful caches and prevents both torch.compile and
cross-process inference (no clean ``network.forward(obs)`` signature).

This wrapper accepts a fully-built obs_dict containing all 15 tensors
that ActorCritic.forward needs (including the cached static fields
that DmcAgent computes per-episode via game_start). Output: raw Q
logits ``(B, max_actions)`` — caller slices ``[:n_legal]``.

Lets:
- LocalNetworkProvider.forward(obs_dict, mask=None) call this network
  directly in-proc (serial mode).
- torch.compile(DMCInferenceNet) wrap the graph.
- InferenceServer pickle this network across spawn boundary; GPU
  batched forward.

Single Q head (DMC_HEAD_KINDS = {'q'}); other heads unused.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn


class DMCInferenceNet(nn.Module):
    """nn.Module wrapping ActorCritic; forward(obs_dict) → q_logits tensor."""

    def __init__(self, actor_critic: nn.Module) -> None:
        super().__init__()
        # add_module so .parameters() + state_dict() walk children naturally.
        self.add_module('net', actor_critic)

    def forward(self, obs: dict, mask: Any = None) -> torch.Tensor:
        """Tensor-shaped DMC inference forward.

        obs must contain ALL 15 tensors that ActorCritic.forward consumes.
        DmcAgent.build_obs_dict packs them (cached static fields from
        game_start + dynamic fields parsed at this turn). mask param
        ignored — DMC handles n_legal slicing externally at the caller.
        """
        out = self.net(
            obs['counter_values'],
            obs['counter_sids'],
            obs['active_slot_mask'],
            obs['hook_emb'],
            obs['hook_mask'],
            obs['card_buckets'],
            obs['enemy_sizes'],
            obs['meta'],
            obs['action_refs'],
            obs['action_payments'],
            obs['structural_values'],
            obs['char_skill_refs'],
            obs['recent_damage'],
            obs['prepare_skill'],
            obs['modifier_log'],
        )
        return out['q']
