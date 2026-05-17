"""Static + dynamic obs encoding for CFR traversal."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import torch

from training.core.obs_constants import (
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_META_SIZE,
    N_STRUCTURAL,
)
from training.core.step_encoding import (
    build_legal_mask,
    pad_action_payments,
    pad_action_refs,
    parse_dynamic_np,
)
from training.core.structural import compute_structural_obspos


@dataclass
class _StaticBundle:
    """Encoded static state for one game."""

    hook_emb: torch.Tensor
    hook_mask_t: torch.Tensor
    counter_sids_t: torch.Tensor
    active_slot_mask_t: torch.Tensor
    char_skill_refs_t: torch.Tensor
    structural_obspos: torch.Tensor
    static_np: dict


def encode_static_for_traversal(
    net,
    static_obs_np: np.ndarray,
    n_counter_slots: int,
    max_tokens_per_hook: int,
    n_hooks_capacity: int,
    device: torch.device,
) -> _StaticBundle:
    """Encode one game's static obs using the AdvantageNet trunk's
    hook_encoder."""
    with torch.no_grad():
        static = torch.tensor(static_obs_np, dtype=torch.float32, device=device)

        meta_size = n_counter_slots * 3
        counter_meta = static[:meta_size].reshape(n_counter_slots, 3)
        active_slot_mask = (counter_meta[:, 0] != 0) | (counter_meta[:, 1] != 0)
        counter_sids = counter_meta[:, 2].long()

        char_skill_refs = (
            static[meta_size : meta_size + OBS_CHAR_SKILL_REFS_SIZE]
            .reshape(2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR)
            .long()
        )

        # Bound the hook slice — the static obs tail now carries
        # OBS_CHAR_ELEMENT_SLOTS ints (char element IDs) after the
        # hook block. Without an explicit upper bound the reshape
        # would include them and fail with an off-by-12 size mismatch.
        hook_size = n_hooks_capacity * max_tokens_per_hook * 2
        hook_data = static[
            meta_size + OBS_CHAR_SKILL_REFS_SIZE : meta_size + OBS_CHAR_SKILL_REFS_SIZE + hook_size
        ].reshape(
            n_hooks_capacity,
            max_tokens_per_hook,
            2,
        )
        hook_types_all = hook_data[:, :, 0].long()
        hook_values_all = hook_data[:, :, 1].float()
        non_empty = hook_types_all.sum(dim=-1) != 0
        n_active = int(non_empty.sum().item())

        if n_active > 0:
            active_types = hook_types_all[non_empty]
            active_values = hook_values_all[non_empty]
            mask_1d = torch.ones(1, n_active, dtype=torch.bool, device=device)
            hook_emb = net.trunk.hook_encoder(
                active_types.unsqueeze(0),
                active_values.unsqueeze(0),
                mask_1d,
            ).squeeze(0)
            hook_mask = torch.ones(n_active, dtype=torch.bool, device=device)
        else:
            hook_emb = torch.zeros(1, net.cfg.d_model, device=device)
            hook_mask = torch.zeros(1, dtype=torch.bool, device=device)
            active_types = torch.zeros(
                1,
                max_tokens_per_hook,
                dtype=torch.long,
                device=device,
            )
            active_values = torch.zeros(
                1,
                max_tokens_per_hook,
                dtype=torch.float32,
                device=device,
            )

    active_slot_mask_1 = active_slot_mask.unsqueeze(0)
    counter_sids_1 = counter_sids.unsqueeze(0)
    char_skill_refs_1 = char_skill_refs.unsqueeze(0)
    structural_obspos = compute_structural_obspos(
        counter_sids_1,
        active_slot_mask_1,
    )

    static_np = {
        'hook_types': active_types.detach().cpu().numpy().astype(np.int64),
        'hook_values': active_values.detach().cpu().numpy().astype(np.float32),
        'hook_mask': hook_mask.detach().cpu().numpy().astype(bool),
        'counter_sids': counter_sids.detach().cpu().numpy().astype(np.int64),
        'active_slot_mask': active_slot_mask.detach().cpu().numpy().astype(bool),
        'char_skill_refs': char_skill_refs.detach().cpu().numpy().astype(np.int64),
    }
    return _StaticBundle(
        hook_emb=hook_emb.unsqueeze(0),
        hook_mask_t=hook_mask.unsqueeze(0),
        counter_sids_t=counter_sids_1,
        active_slot_mask_t=active_slot_mask_1,
        char_skill_refs_t=char_skill_refs_1,
        structural_obspos=structural_obspos,
        static_np=static_np,
    )


def build_dynamic(
    env,
    n_counter_slots: int,
    max_actions: int,
) -> tuple[dict, np.ndarray, int]:
    """Build per-decision dynamic obs dict + legal refs + n_legal."""
    # Round-5 S3: CFR 不消费 typed obs segments(CFRStrategyNet.forward
    # 签名不接收),旧版本 build 后扔进 dict 是 dead emit + 多余 reshape
    # /copy 开销。删 parse_dynamic_typed_np 调用,需要时由 future PR
    # 同步加 CFR 网络消费路径。
    dyn = env._get_obs()
    counter_values, meta, card_buckets, enemy_sizes = parse_dynamic_np(
        dyn,
        n_counter_slots,
        copy=False,
    )

    refs_np = np.asarray(env.get_action_refs(), dtype=np.int32)
    payments_np = np.asarray(env.get_legal_action_payments(), dtype=np.float32)
    n_legal = len(refs_np)
    if n_legal == 0:
        raise RuntimeError('_build_dynamic: no legal actions at decision node')
    if n_legal > max_actions:
        raise ValueError(f'_build_dynamic: n_legal={n_legal} > max_actions={max_actions}')

    action_refs = pad_action_refs(refs_np, max_actions)
    action_payments = pad_action_payments(payments_np, max_actions)
    legal_mask = build_legal_mask(max_actions, n_legal)

    structural_values = np.zeros(N_STRUCTURAL, dtype=np.float32)

    dynamic = {
        'counter_values': counter_values,
        'meta': meta,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'action_refs': action_refs,
        'action_payments': action_payments,
        'legal_mask': legal_mask,
        'structural_values': structural_values,
    }
    return dynamic, refs_np, n_legal
