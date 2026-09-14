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

from training.core.step_encoding import parse_buffs_np
from training.paradigms.dmc._capture_obs import _capture_obs_np as _capture_obs_np
from training.core.network.static_links import parse_definition_links_np


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
        'definition_links': static_cache['definition_links'],
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
        'buffs': torch.as_tensor(parse_buffs_np(payload['dyn_obs'], n_counter_slots), device=device).unsqueeze(0),
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
    definition_links_np = parse_definition_links_np(
        static_obs_np,
        n_counter_slots=n_counter_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_ops_per_hook,
        fields_per_op=fields_per_op,
    )

    from training.core.network.obs_layout import validate_static_layout

    validate_static_layout(static_obs_np, actor_critic)

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
        'definition_links': torch.as_tensor(definition_links_np, dtype=torch.long, device=device).unsqueeze(0),
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
    from training.core.network.obs_layout import validate_static_dimensions
    from training.core.obs_constants import (
        OBS_CHAR_SKILL_REFS_SIZE,
        OBS_MAX_CHARS,
        OBS_MAX_SKILLS_PER_CHAR,
    )

    validate_static_dimensions(static_obs_np, n_counter_slots, n_hooks, max_ops_per_hook, fields_per_op)
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
    definition_links = parse_definition_links_np(
        static_obs_np,
        n_counter_slots=n_counter_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_ops_per_hook,
        fields_per_op=fields_per_op,
    )
    return {
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask.astype(bool),
        'char_skill_refs': char_skill_refs,
        'hook_ir': active_ir,
        'hook_mask': hook_mask,
        'definition_links': definition_links,
    }
