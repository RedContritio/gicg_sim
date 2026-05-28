"""AZ inference-server batched request handlers。

W2-2 (post-2026-05-28):pre-W2-2 这些 handler 住在
``training/core/inference/server_loop/drain.py``,但实现里写死了 AZ obs
schema(15-tensor 解码 + ``out['policy']`` / ``out['value']`` 读法 +
``agent.encode_static_tensors_with_tokens`` 6-tuple 返回约定)— audit
finding 高优 #2,违反 "core algorithm-agnostic" 契约。 搬来 paradigms/az
后 core 仅持 generic dispatch + game_end(纯 cache 删除);eval batch
schema 与 game_start 的 AZ-specific 解码完全 paradigm-local。

调用约定(``core/inference/server_loop/drain.py:_process_batch`` 调):
- ``handle_game_start(agent, cache, req, pipe, state)`` — req 含 worker_id /
  game_id / static_obs;cache key=(worker_id, game_id) 存 hook_emb 等
  6 个 AZ static tensor;pipe 回 game_start_ack。
- ``handle_eval_batch(agent, cache, entries)`` — entries 是 N 条 eval
  request,本 handler stack 成单次 net forward,split 后 N 次 pipe.send
  prior + value。
- ``handle_game_end`` 仍住 core(纯 cache.pop + ack pipe,无 AZ-specific
  schema 依赖)。
"""

from __future__ import annotations

import multiprocessing.connection as mp_conn

import numpy as np


def handle_game_start(agent, cache, req, pipe, state) -> None:
    """AZ game_start handler — encode static obs via AZ Agent + cache。"""
    wid = int(req['worker_id'])
    gid = int(req['game_id'])
    static_obs = req['static_obs']

    (
        hook_emb,
        hook_mask,
        counter_sids,
        active_slot_mask,
        hook_ir,
        char_skill_refs,
    ) = agent.encode_static_tensors_with_tokens(static_obs)
    cache[(wid, gid)] = {
        'hook_emb': hook_emb,
        'hook_mask': hook_mask,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'char_skill_refs': char_skill_refs,
    }
    pipe.send(
        {
            'kind': 'game_start_ack',
            'weight_version': state.weight_version,
            'game_static': {
                'hook_ir': hook_ir.detach().cpu().numpy().astype(np.int64),
                'hook_mask': hook_mask.detach().cpu().numpy().astype(bool),
                'counter_sids': counter_sids.detach().cpu().numpy().astype(np.int64),
                'active_slot_mask': active_slot_mask.detach().cpu().numpy().astype(bool),
                'char_skill_refs': char_skill_refs.detach().cpu().numpy().astype(np.int64),
            },
        }
    )


def handle_eval_batch(
    agent,
    cache: dict[tuple[int, int], dict],
    entries: list[tuple[dict, mp_conn.Connection]],
) -> None:
    """Stack all eval requests into one network forward, split the
    result, send each prior/value back to the originating pipe。"""
    import torch

    from training.core.obs_constants import (
        ACTION_END_TURN,
        DICE_COLOR_COUNT,
        OBS_ENEMY_SIZES,
        OBS_HAND_BUCKETS,
        OBS_MAX_CARD_TYPES,
        OBS_MAX_CHARS,
        OBS_MAX_SKILLS_PER_CHAR,
        OBS_META_SIZE,
        OBS_MODIFIER_LOG_FIELD_COUNT,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_MODIFIER_LOG_SLOTS,  # noqa: F401  — re-export-friendly
        OBS_PREPARE_SKILL_SLOTS,  # noqa: F401
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
        OBS_RECENT_DAMAGE_SLOTS,  # noqa: F401
    )
    from training.core.step_encoding import typed_segment_offsets
    from training.core.structural import (
        compute_structural_obspos,
        compute_structural_values,
    )

    cfg = agent.cfg
    device = agent.device
    B = len(entries)

    n_actives: list[int] = []
    for req, _ in entries:
        key = (int(req['worker_id']), int(req['game_id']))
        if key not in cache:
            raise RuntimeError(f'eval for ungameplay-started key {key} — worker must call game_start before eval')
        n_actives.append(int(cache[key]['hook_emb'].shape[0]))
    max_n_active = max(n_actives)
    D = cfg.d_model

    hook_emb_batch = torch.zeros(B, max_n_active, D, device=device)
    hook_mask_batch = torch.zeros(B, max_n_active, dtype=torch.bool, device=device)
    counter_sids_batch = torch.zeros(B, cfg.n_counter_slots, dtype=torch.long, device=device)
    counter_values_batch = torch.zeros(B, cfg.n_counter_slots, device=device)
    active_slot_mask_batch = torch.zeros(B, cfg.n_counter_slots, dtype=torch.bool, device=device)
    meta_batch = torch.zeros(B, OBS_META_SIZE, device=device)
    card_buckets_batch = torch.zeros(
        B,
        OBS_HAND_BUCKETS,
        OBS_MAX_CARD_TYPES,
        device=device,
    )
    enemy_sizes_batch = torch.zeros(B, OBS_ENEMY_SIZES, device=device)
    # ADR-0019 §B.2/§B.3c typed obs segments
    recent_damage_batch = torch.zeros(
        B,
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
        device=device,
    )
    prepare_skill_batch = torch.zeros(B, 2, 2, device=device)
    modifier_log_batch = torch.zeros(
        B,
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_MODIFIER_LOG_FIELD_COUNT,
        device=device,
    )
    refs_batch = torch.zeros(
        B,
        cfg.max_actions,
        3,
        dtype=torch.long,
        device=device,
    )
    refs_batch[..., 0] = ACTION_END_TURN
    refs_batch[..., 1:] = -1
    pay_batch = torch.zeros(
        B,
        cfg.max_actions,
        DICE_COLOR_COUNT,
        device=device,
    )
    char_skill_refs_batch = torch.full(
        (B, 2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR),
        -1,
        dtype=torch.long,
        device=device,
    )

    n_legals: list[int] = []

    for b, (req, _pipe) in enumerate(entries):
        key = (int(req['worker_id']), int(req['game_id']))
        entry = cache[key]
        n_active = n_actives[b]
        hook_emb_batch[b, :n_active] = entry['hook_emb']
        hook_mask_batch[b, :n_active] = entry['hook_mask']
        counter_sids_batch[b] = entry['counter_sids']
        active_slot_mask_batch[b] = entry['active_slot_mask']
        char_skill_refs_batch[b] = entry['char_skill_refs']

        dyn = torch.as_tensor(req['dyn'], dtype=torch.float32, device=device)
        meta_batch[b] = dyn[:OBS_META_SIZE]
        c_end = OBS_META_SIZE + cfg.n_counter_slots
        counter_values_batch[b] = dyn[OBS_META_SIZE:c_end]
        hand_end = c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
        card_buckets_batch[b] = dyn[c_end:hand_end].view(
            OBS_HAND_BUCKETS,
            OBS_MAX_CARD_TYPES,
        )
        off = typed_segment_offsets(cfg.n_counter_slots)
        enemy_sizes_batch[b] = dyn[hand_end : off['enemy_end']]
        recent_damage_batch[b] = dyn[off['enemy_end'] : off['rd_end']].view(
            OBS_RECENT_DAMAGE_EVENTS,
            OBS_RECENT_DAMAGE_FIELD_COUNT,
        )
        prepare_skill_batch[b] = dyn[off['rd_end'] : off['ps_end']].view(2, 2)
        modifier_log_batch[b] = dyn[off['ps_end'] : off['ml_end']].view(
            OBS_RECENT_DAMAGE_EVENTS,
            OBS_MODIFIER_LOG_K_MOD,
            OBS_MODIFIER_LOG_FIELD_COUNT,
        )

        refs_np = req['refs']
        pay_np = req['payments']
        n_legal = int(len(refs_np))
        if n_legal == 0:
            raise ValueError('server eval: n_legal == 0')
        if n_legal > cfg.max_actions:
            raise ValueError(f'server eval: n_legal={n_legal} exceeds agent max_actions={cfg.max_actions}')
        refs_batch[b, :n_legal] = torch.as_tensor(
            refs_np,
            dtype=torch.long,
            device=device,
        )
        pay_batch[b, :n_legal] = torch.as_tensor(
            pay_np,
            dtype=torch.float32,
            device=device,
        )
        n_legals.append(n_legal)

    with torch.no_grad():
        structural_obspos = compute_structural_obspos(
            counter_sids_batch,
            active_slot_mask_batch,
        )
        structural_values = compute_structural_values(
            counter_values_batch,
            structural_obspos,
        )
        out = agent.net(
            counter_values_batch,
            counter_sids_batch,
            active_slot_mask_batch,
            hook_emb_batch,
            hook_mask_batch,
            card_buckets_batch,
            enemy_sizes_batch,
            meta_batch,
            refs_batch,
            pay_batch,
            structural_values,
            char_skill_refs_batch,
            recent_damage_batch,
            prepare_skill_batch,
            modifier_log_batch,
        )
        # AZ ActorCritic returns dict with 'policy' + 'value' + 'delta' heads。
        logits = out['policy']
        value = out['value']

    for b, (_req, pipe) in enumerate(entries):
        n_legal = n_legals[b]
        legal_logits = logits[b, :n_legal]
        prior = torch.softmax(legal_logits, dim=-1).cpu().numpy().astype(np.float32)
        v_scalar = float(value[b].item())
        pipe.send({'kind': 'eval_ack', 'prior': prior, 'value': v_scalar})
