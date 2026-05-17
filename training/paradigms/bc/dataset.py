"""BC dataset loading + per-game static obs parsing.

Split out of ``training.paradigms.bc.legacy.bc_train`` to keep that file under the
300-line cap. Pure CPU/NumPy code; no torch dependency.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from training.core.obs_constants import (
    OBS_CHAR_SKILL_REFS_SIZE,
    OBS_MAX_CHARS,
    OBS_MAX_SKILLS_PER_CHAR,
    OBS_META_SIZE,
)
from training.core.step_encoding import parse_dynamic_np, parse_dynamic_typed_np


def parse_static_obs_np(
    static_obs: np.ndarray,
    n_counter_slots: int,
    n_hooks: int,
    max_tokens_per_hook: int,
) -> dict:
    """NumPy-only parse of one game's static_obs into the 6 raw fields
    needed by ActorCritic (mirrors agent_base.encode_static_tensors_with_tokens
    but stays offline / no encoder forward).

    Returns dict with keys: hook_types, hook_values, hook_mask,
    counter_sids, active_slot_mask, char_skill_refs.
    """
    s = np.asarray(static_obs)
    meta_size = n_counter_slots * 3
    counter_meta = s[:meta_size].reshape(n_counter_slots, 3)
    active_slot_mask = (counter_meta[:, 0] != 0) | (counter_meta[:, 1] != 0)
    counter_sids = counter_meta[:, 2].astype(np.int64)

    refs_size = OBS_CHAR_SKILL_REFS_SIZE
    char_skill_refs = (
        s[meta_size : meta_size + refs_size].reshape(2, OBS_MAX_CHARS, OBS_MAX_SKILLS_PER_CHAR).astype(np.int64)
    )

    hook_size = n_hooks * max_tokens_per_hook * 2
    hook_data = s[meta_size + refs_size : meta_size + refs_size + hook_size].reshape(
        n_hooks,
        max_tokens_per_hook,
        2,
    )
    hook_types_all = hook_data[:, :, 0].astype(np.int64)
    hook_values_all = hook_data[:, :, 1].astype(np.float32)
    non_empty = hook_types_all.sum(axis=-1) != 0
    active_types = hook_types_all[non_empty]
    active_values = hook_values_all[non_empty]
    n_active = active_types.shape[0]
    hook_mask = np.ones(n_active, dtype=bool) if n_active > 0 else np.zeros(0, dtype=bool)
    return {
        'hook_types': active_types,
        'hook_values': active_values,
        'hook_mask': hook_mask,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'char_skill_refs': char_skill_refs,
    }


def stack_static_batch(statics: list[dict], max_tokens_per_hook: int) -> dict:
    """Pad + stack a list of per-game static dicts to a batch dict."""
    B = len(statics)
    max_n_active = max((s['hook_types'].shape[0] for s in statics), default=1)
    max_n_active = max(max_n_active, 1)
    n_slots = statics[0]['counter_sids'].shape[0]
    csr_shape = statics[0]['char_skill_refs'].shape

    hook_types = np.zeros((B, max_n_active, max_tokens_per_hook), dtype=np.int64)
    hook_values = np.zeros((B, max_n_active, max_tokens_per_hook), dtype=np.float32)
    hook_mask = np.zeros((B, max_n_active), dtype=bool)
    counter_sids = np.zeros((B, n_slots), dtype=np.int64)
    active_slot_mask = np.zeros((B, n_slots), dtype=bool)
    char_skill_refs = np.zeros((B,) + csr_shape, dtype=np.int64)

    for i, s in enumerate(statics):
        n = s['hook_types'].shape[0]
        if n > 0:
            hook_types[i, :n] = s['hook_types']
            hook_values[i, :n] = s['hook_values']
            hook_mask[i, :n] = s['hook_mask']
        counter_sids[i] = s['counter_sids']
        active_slot_mask[i] = s['active_slot_mask']
        char_skill_refs[i] = s['char_skill_refs']

    return {
        'hook_types': hook_types,
        'hook_values': hook_values,
        'hook_mask': hook_mask,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'char_skill_refs': char_skill_refs,
    }


class BCDataset:
    """Loads NPZ + caches per-game parsed static.

    game_static_obs is HUGE (4629 games × 221k floats ≈ 4 GB for our
    Stage 3 dataset because of 900 hooks × 120 tokens). We parse all
    games immediately into compact (n_active × max_tokens) arrays and
    drop the raw static obs to keep RAM bounded.
    """

    def __init__(self, npz_path: Path, n_counter_slots: int, n_hooks: int, max_tokens_per_hook: int):
        d = np.load(npz_path)
        self.game_id = np.ascontiguousarray(d['game_id'])
        self.dyn_obs = np.ascontiguousarray(d['dyn_obs'])
        self.action_refs = np.ascontiguousarray(d['action_refs'])
        self.action_payments = np.ascontiguousarray(d['action_payments'])
        self.legal_mask = np.ascontiguousarray(d['legal_mask'])
        self.tied_mask = np.ascontiguousarray(d['tied_mask'])
        self.chosen_action = np.ascontiguousarray(d['chosen_action'])
        self.terminal_z = np.ascontiguousarray(d['terminal_z'])
        self.n_decisions = self.chosen_action.shape[0]
        self.n_counter_slots = n_counter_slots
        self.n_hooks = n_hooks
        self.max_tokens_per_hook = max_tokens_per_hook

        unique_gids = np.unique(self.game_id)
        raw_static_arr = d['game_static_obs']
        self._parsed_statics: dict[int, dict] = {}
        for gid in unique_gids:
            self._parsed_statics[int(gid)] = parse_static_obs_np(
                raw_static_arr[int(gid)],
                n_counter_slots,
                n_hooks,
                max_tokens_per_hook,
            )
        del raw_static_arr
        d.close()
        import gc

        gc.collect()

    def __len__(self) -> int:
        return self.n_decisions

    def build_batch(self, indices: np.ndarray) -> dict:
        """Construct the 12+ field batch dict for ActorCritic.forward_batch
        from a list of decision indices."""
        statics = [self._parsed_statics[int(self.game_id[i])] for i in indices]
        static_batch = stack_static_batch(statics, self.max_tokens_per_hook)

        B = len(indices)
        counter_values = np.zeros((B, self.n_counter_slots), dtype=np.float32)
        meta = np.zeros((B, OBS_META_SIZE), dtype=np.float32)
        sample = parse_dynamic_np(self.dyn_obs[indices[0]], self.n_counter_slots, copy=True)
        card_buckets = np.zeros((B,) + sample[2].shape, dtype=np.float32)
        enemy_sizes = np.zeros((B,) + sample[3].shape, dtype=np.float32)
        # ADR-0019 §B.2/§B.3c typed segments
        td_sample = parse_dynamic_typed_np(
            self.dyn_obs[indices[0]],
            self.n_counter_slots,
            copy=True,
            include_modifier_log=True,
        )
        recent_damage = np.zeros((B,) + td_sample[0].shape, dtype=np.float32)
        prepare_skill = np.zeros((B,) + td_sample[1].shape, dtype=np.float32)
        modifier_log = np.zeros((B,) + td_sample[2].shape, dtype=np.float32)
        for j, i in enumerate(indices):
            cv, m, cb, es = parse_dynamic_np(self.dyn_obs[i], self.n_counter_slots, copy=True)
            counter_values[j] = cv
            meta[j] = m
            card_buckets[j] = cb
            enemy_sizes[j] = es
            rd, ps, ml = parse_dynamic_typed_np(
                self.dyn_obs[i],
                self.n_counter_slots,
                copy=True,
                include_modifier_log=True,
            )
            recent_damage[j] = rd
            prepare_skill[j] = ps
            modifier_log[j] = ml

        return {
            **static_batch,
            'counter_values': counter_values,
            'meta': meta,
            'card_buckets': card_buckets,
            'enemy_sizes': enemy_sizes,
            'recent_damage': recent_damage,
            'prepare_skill': prepare_skill,
            'modifier_log': modifier_log,
            'action_refs': self.action_refs[indices],
            'action_payments': self.action_payments[indices],
            'legal_mask': self.legal_mask[indices],
            'tied_mask': self.tied_mask[indices],
            'chosen_action': self.chosen_action[indices],
            'terminal_z': self.terminal_z[indices],
        }
