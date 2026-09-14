"""BCNetwork — thin nn.Module wrapper around ActorCritic for driver compat.

The current network contains policy, value, and delta heads. With the default
``value_coef = 0.0``, the BC loss supplies gradients only through the policy
path; cross-paradigm checkpoint compatibility still depends on the actual
state-dict and observation schema.

Spec ref: paradigm-bc/spec.md BC4. The encoder is paradigm-agnostic — we
reuse generic ``training.core.network.ActorCritic`` (via make_actor_critic).
The wrapper exposes ``forward_batch(batch_dict)`` (used by BCLoss) on top
of standard nn.Module API so the driver can hand it to the optimizer.
"""

from __future__ import annotations

from typing import Any

import torch
import torch.nn as nn

from training.core.network import ActorCritic, make_actor_critic
from training.paradigms.bc.config import AgentShapeCfg


# BC keeps all 3 heads (policy + value + delta) on the generic typed-observation
# backbone. Matching head names alone does not establish checkpoint compatibility.
BC_HEAD_KINDS = frozenset({'policy', 'value', 'delta'})


class BCNetwork(nn.Module):
    """nn.Module wrapper exposing ActorCritic + a ``forward_batch`` shim
    that matches bc._train_loss.forward_batch's signature (BC dataset dict).

    The wrapped ActorCritic includes value + delta heads;BC training
    only backpropagates through policy head when cfg.value_coef = 0.0
    (BC4.1)。ckpt round-trip preserves all heads so AZ/PPO/DMC can
    init_from_ckpt 共享 encoder。
    """

    def __init__(self, agent_cfg: AgentShapeCfg, device: str = 'cpu') -> None:
        super().__init__()
        self._net = make_actor_critic(
            agent_cfg,
            head_kinds=BC_HEAD_KINDS,
            use_typed_damage=True,
        )
        self._device = torch.device(device)
        self._net.to(self._device)
        # Register as child so .parameters() / .state_dict() walk it.
        self.add_module('net', self._net)

    @property
    def actor_critic(self) -> ActorCritic:
        return self._net

    def forward_batch(self, batch: dict) -> tuple:
        """Run ActorCritic forward on a BC dataset dict (12+ fields from
        BCDataset.build_batch). Returns (logits, value).

        The implementation is local to the current BC package; retired legacy
        paths are not imported.
        """
        from training.core.structural import (
            compute_structural_obspos,
            compute_structural_values,
        )

        device = self._device

        def _t(key: str, dtype: torch.dtype) -> torch.Tensor:
            return torch.as_tensor(batch[key], dtype=dtype, device=device)

        counter_values = _t('counter_values', torch.float32)
        counter_sids = _t('counter_sids', torch.long)
        active_slot_mask = _t('active_slot_mask', torch.bool)
        hook_ir = _t('hook_ir', torch.long)
        hook_mask = _t('hook_mask', torch.bool)
        card_buckets = _t('card_buckets', torch.float32)
        enemy_sizes = _t('enemy_sizes', torch.float32)
        meta = _t('meta', torch.float32)
        action_refs = _t('action_refs', torch.long)
        action_payments = _t('action_payments', torch.float32)
        char_skill_refs = _t('char_skill_refs', torch.long)
        definition_links = _t('definition_links', torch.long)
        recent_damage = _t('recent_damage', torch.float32)
        prepare_skill = _t('prepare_skill', torch.float32)
        modifier_log = _t('modifier_log', torch.float32)

        hook_emb = self._net.hook_encoder(hook_ir, hook_mask)
        structural_obspos = compute_structural_obspos(counter_sids, active_slot_mask)
        structural_values = compute_structural_values(counter_values, structural_obspos)

        out = self._net(
            counter_values,
            counter_sids,
            active_slot_mask,
            hook_emb,
            hook_mask,
            card_buckets,
            enemy_sizes,
            meta,
            action_refs,
            action_payments,
            structural_values,
            char_skill_refs,
            recent_damage,
            prepare_skill,
            modifier_log,
            buffs=_t('buffs', torch.float32) if 'buffs' in batch else None,
            definition_links=definition_links,
        )
        return out['policy'], out['value']

    def forward(self, *args: Any, **kwargs: Any) -> Any:  # pragma: no cover
        raise NotImplementedError('BCNetwork.forward not used — call forward_batch(batch_dict) instead.')
