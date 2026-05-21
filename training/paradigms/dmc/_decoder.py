"""DMC inference-server request decoder + numpy obs helpers.

Split from ``mp_factories.py`` for file-budget. Server side:
``decode_dmc_request`` decodes the actor's numpy IPC payload + builds
the 15-tensor obs_dict on device, reusing the server's live
:class:`HookIREncoder` for per-game static encoding (cached in
``client_cache['static']``). Actor side: ``_encode_static_np`` +
``_capture_obs_np`` mirror :func:`capture_obs` in pure numpy so the
actor process never imports torch for buffer-side obs assembly.

See ``mp_factories.py`` module docstring for architectural rationale.
"""

from __future__ import annotations

import pickle
from typing import Any

import numpy as np


def decode_dmc_request(
    obs_bytes: bytes,
    mask_bytes: bytes,
    device_str: str,
    shared_cache: dict,
    network: Any,
) -> tuple[dict, Any]:
    """Server-side decoder for DMC numpy payloads.

    Unpickles the actor's numpy payload, looks up
    ``shared_cache[static_obs_hash]`` (server-wide cache shared across
    all clients — fixed-scenario DMC runs encode hook_encoder ONCE
    total, not once per actor×episode). On cache miss, runs
    :func:`_server_encode_static` (hook_encoder forward + static parse)
    against the server's live weights, stores under the hash key.

    Parses the dynamic obs into 7 typed tensors, builds the 15-tensor
    obs_dict for :class:`DMCInferenceNet.forward`. Returns
    ``(obs_dict, None)`` — mask unused (DMC slices n_legal at the
    actor).
    """
    import torch

    from training.core.step_encoding import typed_segment_offsets
    from training.core.structural import compute_structural_values
    from training.core.obs_constants import (
        OBS_HAND_BUCKETS,
        OBS_MAX_CARD_TYPES,
        OBS_META_SIZE,
        OBS_MODIFIER_LOG_FIELD_COUNT,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
    )

    payload = pickle.loads(obs_bytes)
    device = torch.device(device_str)

    # Weight-update interaction: ``InferenceServer`` wipes ``shared_cache``
    # on weight load so static embeddings recompute on next request. Cache
    # is server-wide keyed by static_obs hash: multiple actors with the
    # same scenario share one cache entry (encode runs ONCE total). Each
    # forward sends the hash; the static_obs bytes are only embedded on
    # game_start (or whenever the hash misses) — server resolves miss by
    # re-encoding from the embedded static_obs. If both miss + no
    # static_obs sent (e.g. mid-game weight update + actor unaware),
    # raise loudly rather than silently using stale embedding.
    static_obs_hash = payload.get('static_obs_hash')
    if static_obs_hash is None:
        raise RuntimeError('decode_dmc_request: payload missing static_obs_hash')
    static_cache = shared_cache.get(static_obs_hash)
    if static_cache is None:
        static_obs_np = payload.get('static_obs')
        if static_obs_np is None:
            raise RuntimeError(
                f'decode_dmc_request: cache miss for hash={static_obs_hash.hex()[:12]}... '
                f'with no embedded static_obs. Actor must resend static_obs after weight update.'
            )
        static_cache = _server_encode_static(static_obs_np, device, network)
        shared_cache[static_obs_hash] = static_cache

    # ---- Dynamic obs → 7 typed tensors ---- #
    dyn_obs = payload['dyn_obs']
    n_counter_slots = static_cache['n_counter_slots']
    dyn = torch.from_numpy(np.ascontiguousarray(dyn_obs, dtype=np.float32)).unsqueeze(0).to(device)
    meta = dyn[:, :OBS_META_SIZE]
    c_end = OBS_META_SIZE + n_counter_slots
    counter_values = dyn[:, OBS_META_SIZE:c_end]
    hand_end = c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
    card_buckets = dyn[:, c_end:hand_end].view(1, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    off = typed_segment_offsets(n_counter_slots)
    enemy_sizes = dyn[:, hand_end : off['enemy_end']]
    recent_damage = dyn[:, off['enemy_end'] : off['rd_end']].view(
        1, OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT
    )
    prepare_skill = dyn[:, off['rd_end'] : off['ps_end']].view(1, 2, 2)
    modifier_log = dyn[:, off['ps_end'] : off['ml_end']].view(
        1, OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT
    )

    # ---- Per-turn padded action inputs ---- #
    refs_t = torch.from_numpy(np.ascontiguousarray(payload['refs_padded'], dtype=np.int64)).unsqueeze(0).to(device)
    pay_t = torch.from_numpy(np.ascontiguousarray(payload['pay_padded'], dtype=np.float32)).unsqueeze(0).to(device)

    structural_values = compute_structural_values(counter_values, static_cache['structural_obspos'])

    obs_dict = {
        'counter_values': counter_values,
        'counter_sids': static_cache['counter_sids'],
        'active_slot_mask': static_cache['active_slot_mask'],
        'hook_emb': static_cache['hook_emb'],
        'hook_mask': static_cache['hook_mask'],
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'meta': meta,
        'action_refs': refs_t,
        'action_payments': pay_t,
        'structural_values': structural_values,
        'char_skill_refs': static_cache['char_skill_refs'],
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
    }
    return obs_dict, None


def decode_dmc_requests(
    payloads: list,
    device_str: str,
    shared_cache: dict,
    network: Any,
) -> tuple[dict, Any]:
    """Batched server-side decoder — N requests → 1 obs_dict with batch dim N。

    数值等价于 ``torch.cat([decode_dmc_request(p, ...)[0][k] for p in payloads], dim=0)``
    per key, 但只跑 1 次 ``torch.from_numpy + .to(device)`` per stacked tensor
    (而非 N 次)。production 2026-05-21 实测 InfServer decode 35.7 ms / batch=14
    (69% wall),wins 主要来自 H2D + GPU op launch overhead 砍 N×。

    ``payloads`` items 是 (obs_bytes, mask_bytes) tuple — 与 ``request_decoder``
    单 request 接口对齐(server 把整 batch 传给 batched_decoder 而不是 N 次
    单 decode)。 mask 在 DMC 路径上不消费,忽略。

    Assumption:N requests 共享 ``static_obs_hash``(production single-scenario
    保证 — 全 actor 同 team / 同 card_pool)。 缓存异构 fallback 退化为
    per-request 决策(罕见 — 例:weight update 跨多个 actor mid-game,部分
    actor 已 evict cache 部分未)。

    Returns ``(obs_dict_batched, None)``。
    """
    import torch

    from training.core.obs_constants import (
        OBS_HAND_BUCKETS,
        OBS_MAX_CARD_TYPES,
        OBS_META_SIZE,
        OBS_MODIFIER_LOG_FIELD_COUNT,
        OBS_MODIFIER_LOG_K_MOD,
        OBS_RECENT_DAMAGE_EVENTS,
        OBS_RECENT_DAMAGE_FIELD_COUNT,
    )
    from training.core.step_encoding import typed_segment_offsets
    from training.core.structural import compute_structural_values

    n = len(payloads)
    if n == 0:
        raise ValueError('decode_dmc_requests: empty payloads')
    device = torch.device(device_str)

    # 1. CPU unpickle all + resolve static cache per-request.
    unpickled = [pickle.loads(obs_bytes) for (obs_bytes, _mask) in payloads]
    static_caches: list = []
    for p in unpickled:
        static_obs_hash = p.get('static_obs_hash')
        if static_obs_hash is None:
            raise RuntimeError('decode_dmc_requests: payload missing static_obs_hash')
        sc = shared_cache.get(static_obs_hash)
        if sc is None:
            static_obs_np = p.get('static_obs')
            if static_obs_np is None:
                raise RuntimeError(
                    f'decode_dmc_requests: cache miss for hash={static_obs_hash.hex()[:12]}... '
                    f'with no embedded static_obs. Actor must resend static_obs after weight update.'
                )
            sc = _server_encode_static(static_obs_np, device, network)
            shared_cache[static_obs_hash] = sc
        static_caches.append(sc)

    # 2. Heterogeneous static cache fallback — production 极罕见,直接 per-request
    # decode + cat。 不复杂但仍 N× launch overhead — 罕见路径接受次优。
    same_static = all(sc is static_caches[0] for sc in static_caches)
    if not same_static:
        # Fallback: decode each + cat. Imports lazy。
        per_request_dicts = []
        for (obs_bytes, mask_bytes), _sc in zip(payloads, static_caches):
            d, _ = decode_dmc_request(obs_bytes, mask_bytes, device_str, shared_cache, network)
            per_request_dicts.append(d)
        # cat all keys along batch dim 0(各 dict 各字段 first dim=1)。
        keys = list(per_request_dicts[0].keys())
        return {k: torch.cat([d[k] for d in per_request_dicts], dim=0) for k in keys}, None

    sc0 = static_caches[0]
    n_counter_slots = sc0['n_counter_slots']

    # 3. Stack dyn / refs / pay numpy arrays → single tensor each (1 H2D each).
    dyn_np = np.stack(
        [np.ascontiguousarray(p['dyn_obs'], dtype=np.float32) for p in unpickled],
        axis=0,
    )  # (N, dyn_dim)
    refs_np = np.stack(
        [np.ascontiguousarray(p['refs_padded'], dtype=np.int64) for p in unpickled],
        axis=0,
    )
    pay_np = np.stack(
        [np.ascontiguousarray(p['pay_padded'], dtype=np.float32) for p in unpickled],
        axis=0,
    )
    dyn = torch.from_numpy(dyn_np).to(device)
    refs_t = torch.from_numpy(refs_np).to(device)
    pay_t = torch.from_numpy(pay_np).to(device)

    # 4. Slice dynamic obs into typed (N, ...) tensors — same offsets as
    # decode_dmc_request 单 request 路径,只是 batch dim N。
    meta = dyn[:, :OBS_META_SIZE]
    c_end = OBS_META_SIZE + n_counter_slots
    counter_values = dyn[:, OBS_META_SIZE:c_end]
    hand_end = c_end + OBS_HAND_BUCKETS * OBS_MAX_CARD_TYPES
    card_buckets = dyn[:, c_end:hand_end].view(n, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    off = typed_segment_offsets(n_counter_slots)
    enemy_sizes = dyn[:, hand_end : off['enemy_end']]
    recent_damage = dyn[:, off['enemy_end'] : off['rd_end']].view(
        n, OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT
    )
    prepare_skill = dyn[:, off['rd_end'] : off['ps_end']].view(n, 2, 2)
    modifier_log = dyn[:, off['ps_end'] : off['ml_end']].view(
        n, OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT
    )

    # 5. Static fields:全 N request 共 cache → expand 到 batch dim N 无 copy。
    counter_sids = sc0['counter_sids'].expand(n, -1)
    active_slot_mask = sc0['active_slot_mask'].expand(n, -1)
    hook_emb = sc0['hook_emb'].expand(n, -1, -1)
    hook_mask = sc0['hook_mask'].expand(n, -1)
    char_skill_refs = sc0['char_skill_refs'].expand(n, -1, -1, -1)
    structural_obspos_b = sc0['structural_obspos'].expand(n, -1)

    structural_values = compute_structural_values(counter_values, structural_obspos_b)

    obs_dict = {
        'counter_values': counter_values,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'hook_emb': hook_emb,
        'hook_mask': hook_mask,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'meta': meta,
        'action_refs': refs_t,
        'action_payments': pay_t,
        'structural_values': structural_values,
        'char_skill_refs': char_skill_refs,
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
    }
    return obs_dict, None


def _server_encode_static(static_obs_np: np.ndarray, device: Any, network: Any) -> dict:
    """Encode static obs server-side, reusing ``network.net.hook_encoder``
    (the server's live :class:`HookIREncoder`) so static embeddings
    track the latest weights. Mirrors
    :meth:`AgentBase.encode_static_tensors_with_tokens`.
    """
    import torch

    from training.core.obs_constants import (
        OBS_CHAR_SKILL_REFS_SIZE,
        OBS_MAX_CHARS,
        OBS_MAX_SKILLS_PER_CHAR,
    )
    from training.core.structural import compute_structural_obspos

    # ActorCritic stores shape ints needed for slicing the static obs.
    actor_critic = network.net if hasattr(network, 'net') else network
    hook_encoder = actor_critic.hook_encoder
    n_counter_slots = int(actor_critic.n_counter_slots)
    n_hooks = int(actor_critic.n_hooks)
    max_ops_per_hook = int(actor_critic.max_ops_per_hook)
    fields_per_op = int(actor_critic.fields_per_op)
    d_model = int(actor_critic.d_model)

    with torch.no_grad():
        static = torch.from_numpy(np.ascontiguousarray(static_obs_np, dtype=np.float32)).to(device)
        meta_size = n_counter_slots * 3
        counter_meta = static[:meta_size].reshape(n_counter_slots, 3)
        active_slot_mask = (counter_meta[:, 0] != 0) | (counter_meta[:, 1] != 0)
        counter_sids = counter_meta[:, 2].long()

        refs_size = OBS_CHAR_SKILL_REFS_SIZE
        char_skill_refs = (
            static[meta_size : meta_size + refs_size].reshape(2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR).long()
        )

        hook_size = n_hooks * max_ops_per_hook * fields_per_op
        hook_ir_all = (
            static[meta_size + refs_size : meta_size + refs_size + hook_size]
            .reshape(n_hooks, max_ops_per_hook, fields_per_op)
            .long()
        )
        opcodes_all = hook_ir_all[:, :, 0]
        non_empty = (opcodes_all != 0).any(dim=-1)
        n_active = int(non_empty.sum().item())

        if n_active > 0:
            active_ir = hook_ir_all[non_empty]
            active_mask = torch.ones(1, n_active, dtype=torch.bool, device=device)
            hook_emb = hook_encoder(active_ir.unsqueeze(0), active_mask).squeeze(0)
            hook_mask = torch.ones(n_active, dtype=torch.bool, device=device)
        else:
            hook_emb = torch.zeros(1, d_model, device=device)
            hook_mask = torch.zeros(1, dtype=torch.bool, device=device)

        counter_sids_b = counter_sids.unsqueeze(0)
        active_slot_mask_b = active_slot_mask.unsqueeze(0)
        hook_emb_b = hook_emb.unsqueeze(0)
        hook_mask_b = hook_mask.unsqueeze(0)
        char_skill_refs_b = char_skill_refs.unsqueeze(0)
        structural_obspos = compute_structural_obspos(counter_sids_b, active_slot_mask_b)
    return {
        'counter_sids': counter_sids_b,
        'active_slot_mask': active_slot_mask_b,
        'hook_emb': hook_emb_b,
        'hook_mask': hook_mask_b,
        'char_skill_refs': char_skill_refs_b,
        'structural_obspos': structural_obspos,
        'n_counter_slots': n_counter_slots,
    }


def _encode_static_np(
    static_obs_np: np.ndarray,
    *,
    n_counter_slots: int,
    n_hooks: int,
    max_ops_per_hook: int,
    fields_per_op: int,
) -> dict:
    """Numpy mirror of static parse minus ``hook_emb`` (a nn.Module
    forward — server-side only). Returns the fields ``capture_obs``
    consumes for buffer reconstruction.
    """
    from training.core.obs_constants import (
        OBS_CHAR_SKILL_REFS_SIZE,
        OBS_MAX_CHARS,
        OBS_MAX_SKILLS_PER_CHAR,
    )

    meta_size = n_counter_slots * 3
    counter_meta = static_obs_np[:meta_size].reshape(n_counter_slots, 3)
    active_slot_mask = (counter_meta[:, 0] != 0) | (counter_meta[:, 1] != 0)
    counter_sids = counter_meta[:, 2].astype(np.int64)

    refs_size = OBS_CHAR_SKILL_REFS_SIZE
    char_skill_refs = (
        static_obs_np[meta_size : meta_size + refs_size]
        .reshape(2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR)
        .astype(np.int64)
    )

    hook_size = n_hooks * max_ops_per_hook * fields_per_op
    hook_ir_all = (
        static_obs_np[meta_size + refs_size : meta_size + refs_size + hook_size]
        .reshape(n_hooks, max_ops_per_hook, fields_per_op)
        .astype(np.int64)
    )
    opcodes_all = hook_ir_all[:, :, 0]
    non_empty = (opcodes_all != 0).any(axis=-1)
    n_active = int(non_empty.sum())
    if n_active > 0:
        active_ir = hook_ir_all[non_empty]
        hook_mask = np.ones(n_active, dtype=bool)
    else:
        active_ir = np.zeros((1, max_ops_per_hook, fields_per_op), dtype=np.int64)
        hook_mask = np.zeros(1, dtype=bool)
    return {
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask.astype(bool),
        'char_skill_refs': char_skill_refs,
        'hook_ir': active_ir,
        'hook_mask': hook_mask,
    }


def _capture_obs_np(
    *,
    dyn_obs: np.ndarray,
    n_legal: int,
    refs_padded: np.ndarray,
    pay_padded: np.ndarray,
    max_actions: int,
    n_counter_slots: int,
    static_np: dict,
) -> dict:
    """Pure-numpy mirror of
    :func:`training.paradigms.dmc._episode.capture_obs` — lets the actor
    build the buffer-side obs_dict without importing torch. Returns
    ``{}`` on ``n_legal == 0`` (matches legacy early return).
    """
    if n_legal == 0:
        return {}
    from training.core.step_encoding import (
        build_legal_mask,
        parse_dynamic_np,
        parse_dynamic_typed_np,
    )

    counter_values, meta, card_buckets, enemy_sizes = parse_dynamic_np(dyn_obs, n_counter_slots, copy=True)
    recent_damage, prepare_skill, modifier_log = parse_dynamic_typed_np(
        dyn_obs,
        n_counter_slots,
        copy=True,
        include_modifier_log=True,
    )
    legal_mask = build_legal_mask(max_actions, n_legal)

    return {
        'counter_values': counter_values,
        'meta': meta,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
        'action_refs': refs_padded.astype(np.int64),
        'action_payments': pay_padded.astype(np.float32),
        'legal_mask': legal_mask.astype(bool),
        'n_legal': n_legal,
        'counter_sids': static_np['counter_sids'],
        'active_slot_mask': static_np['active_slot_mask'],
        'char_skill_refs': static_np['char_skill_refs'],
        'hook_ir': static_np['hook_ir'],
        'hook_mask': static_np['hook_mask'],
    }
