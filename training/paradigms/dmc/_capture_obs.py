"""Numpy observation capture for DMC actor requests."""

import numpy as np

from training.core.step_encoding import parse_buffs_np


def _capture_obs_np(
    *,
    dyn_obs: np.ndarray,
    n_legal: int,
    refs_nlegal: np.ndarray,
    pay_nlegal: np.ndarray,
    n_counter_slots: int,
    static_np: dict,
) -> dict:
    """Pure-numpy mirror of
    :func:`training.paradigms.dmc._episode.capture_obs` — lets the actor
    build the buffer-side obs_dict without importing torch. Returns
    ``{}`` on ``n_legal == 0`` (matches legacy early return).

    I29 P2 (wire v3): refs/pay/legal_mask 存 nlegal-sized,不 pad 到 max_actions
    (per-trans mem ~10x 降)。 collate_batch sample 时 pad 到 cfg.max_actions。
    """
    if n_legal == 0:
        return {}
    from training.core.step_encoding import (
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

    return {
        'counter_values': counter_values,
        'meta': meta,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
        'buffs': parse_buffs_np(dyn_obs, n_counter_slots),
        # nlegal-sized (per-trans),collate_batch pad 到 cfg.max_actions for batch。
        'action_refs': refs_nlegal.astype(np.int64),
        'action_payments': pay_nlegal.astype(np.float32),
        # 全 True 长 nlegal — pad 后 batch (B, max_actions) bool 由 collate_batch 算。
        'legal_mask': np.ones(n_legal, dtype=bool),
        'n_legal': n_legal,
        'counter_sids': static_np['counter_sids'],
        'active_slot_mask': static_np['active_slot_mask'],
        'char_skill_refs': static_np['char_skill_refs'],
        'hook_ir': static_np['hook_ir'],
        'hook_mask': static_np['hook_mask'],
        'definition_links': static_np['definition_links'],
    }
