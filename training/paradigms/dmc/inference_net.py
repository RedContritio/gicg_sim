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
            buffs=obs.get('buffs'),
            definition_links=obs['definition_links'],
        )
        return out['q']

    def batched_forward(self, obs_list: list[dict]) -> torch.Tensor:
        """Stack N single-request obs_dicts → 1 batched forward → (N, max_actions) Q logits.

        Variable-length fields (``hook_emb``, ``hook_mask``) padded to
        batch-max ``n_active`` with zero embeddings + False mask; the
        cross-attention pipeline masks out padded positions so valid
        rows are not contaminated. Fixed-shape fields concat'd along
        batch dim 0.

        Numerically equivalent to
        ``torch.cat([self.forward(obs_i) for obs_i in obs_list], dim=0)``
        but with one underlying ActorCritic.forward call for GPU
        efficiency. ``InferenceServer`` activates this path whenever the
        wrapped network exposes ``batched_forward`` and batch size > 1.
        """
        n = len(obs_list)
        if n == 0:
            raise ValueError('DMCInferenceNet.batched_forward: empty obs_list')
        if n == 1:
            # Degenerate — same as forward(); avoid stack overhead.
            return self.forward(obs_list[0])

        # Fixed-shape fields: concat along batch dim 0. Each entry in
        # obs_list has these as (1, ...) tensors from build_obs_dict.
        fixed_keys = (
            'counter_values',
            'counter_sids',
            'active_slot_mask',
            'card_buckets',
            'enemy_sizes',
            'meta',
            'action_refs',
            'action_payments',
            'structural_values',
            'char_skill_refs',
            'recent_damage',
            'prepare_skill',
            'modifier_log',
        )
        batched = {k: torch.cat([o[k] for o in obs_list], dim=0) for k in fixed_keys}
        if any('buffs' in o for o in obs_list) and not all('buffs' in o for o in obs_list):
            raise ValueError('mixed buff observation schemas in inference batch')
        if all('buffs' in o for o in obs_list):
            longest = max(o['buffs'].shape[1] for o in obs_list)
            batched['buffs'] = torch.cat(
                [torch.nn.functional.pad(o['buffs'], (0, 0, 0, longest - o['buffs'].shape[1])) for o in obs_list], dim=0
            )

        max_links = max(o['definition_links'].shape[1] for o in obs_list)
        batched['definition_links'] = torch.cat(
            [
                torch.nn.functional.pad(
                    o['definition_links'], (0, 0, 0, max_links - o['definition_links'].shape[1]), value=-1
                )
                for o in obs_list
            ],
            dim=0,
        )

        # Variable-length fields: hook_emb is (1, n_active_i, D),
        # hook_mask is (1, n_active_i). Pad to batch-max n_active across
        # all requests; padded positions get zero emb + False mask so
        # CrossAttentionBlock + masked pooling ignore them.
        hook_embs = [o['hook_emb'] for o in obs_list]
        hook_masks = [o['hook_mask'] for o in obs_list]
        max_n_active = max(he.shape[1] for he in hook_embs)
        d = hook_embs[0].shape[2]
        device = hook_embs[0].device
        dtype = hook_embs[0].dtype

        padded_hook_emb = torch.zeros(n, max_n_active, d, dtype=dtype, device=device)
        padded_hook_mask = torch.zeros(n, max_n_active, dtype=torch.bool, device=device)
        for i, (he, hm) in enumerate(zip(hook_embs, hook_masks)):
            na = he.shape[1]
            padded_hook_emb[i, :na, :] = he[0]
            padded_hook_mask[i, :na] = hm[0]
        batched['hook_emb'] = padded_hook_emb
        batched['hook_mask'] = padded_hook_mask

        out = self.net(
            batched['counter_values'],
            batched['counter_sids'],
            batched['active_slot_mask'],
            batched['hook_emb'],
            batched['hook_mask'],
            batched['card_buckets'],
            batched['enemy_sizes'],
            batched['meta'],
            batched['action_refs'],
            batched['action_payments'],
            batched['structural_values'],
            batched['char_skill_refs'],
            batched['recent_damage'],
            batched['prepare_skill'],
            batched['modifier_log'],
            buffs=batched.get('buffs'),
            definition_links=batched['definition_links'],
        )
        return out['q']
