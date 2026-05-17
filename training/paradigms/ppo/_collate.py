"""Collate helper — list[Transition] → structural batch dict.

Split from collector.py for the 300-line cap. Used by PPOLoss.compute
(path A) to replay agent.forward_batch on a minibatch sampled from
RolloutBuffer. Mirror of DMC ``collate_batch`` shape.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from training.core.protocols import Transition


def transitions_to_collated(
    transitions: list[Transition],
    agent: Any,
) -> dict:
    """Collate a list of Transitions into a structural batch dict.

    Caller must have called ``agent.game_start(env.static_obs)`` at
    least once so the static cache (hook_emb / counter_sids / etc) is
    populated. PPO rollouts within a single iter share scenario →
    static obs is identical across transitions, so a single cached
    snapshot suffices for the whole minibatch.
    """
    if not transitions:
        raise ValueError('transitions_to_collated: empty transition list')

    B = len(transitions)
    if agent._hook_emb is None:
        raise RuntimeError(
            'transitions_to_collated: agent.game_start has not been called — '
            'cannot collate without static cache. Ensure rollout collector '
            'calls agent.game_start before transitions reach the loss.'
        )

    # Per-step dynamic + action tensors (parse each transition).
    counter_values_list: list[np.ndarray] = []
    meta_list: list[np.ndarray] = []
    card_buckets_list: list[np.ndarray] = []
    enemy_sizes_list: list[np.ndarray] = []
    recent_damage_list: list[np.ndarray] = []
    prepare_skill_list: list[np.ndarray] = []
    modifier_log_list: list[np.ndarray] = []

    refs_list: list[np.ndarray] = []
    payments_list: list[np.ndarray] = []
    n_legal_arr = np.zeros(B, dtype=np.int64)

    for i, t in enumerate(transitions):
        p = t.payload
        (
            counter_values_t,
            meta_t,
            card_buckets_t,
            enemy_sizes_t,
            recent_damage_t,
            prepare_skill_t,
            modifier_log_t,
        ) = agent._parse_dynamic_single(p['dyn_obs'])
        counter_values_list.append(counter_values_t.squeeze(0).cpu().numpy())
        meta_list.append(meta_t.squeeze(0).cpu().numpy())
        card_buckets_list.append(card_buckets_t.squeeze(0).cpu().numpy())
        enemy_sizes_list.append(enemy_sizes_t.squeeze(0).cpu().numpy())
        recent_damage_list.append(recent_damage_t.squeeze(0).cpu().numpy())
        prepare_skill_list.append(prepare_skill_t.squeeze(0).cpu().numpy())
        modifier_log_list.append(modifier_log_t.squeeze(0).cpu().numpy())
        refs_list.append(p['refs'])
        payments_list.append(p['payments'])
        n_legal_arr[i] = int(p['n_legal'])

    ma = agent.cfg.max_actions
    legal_mask = np.zeros((B, ma), dtype=bool)
    for i in range(B):
        legal_mask[i, : n_legal_arr[i]] = True

    # Static fields — replicated to batch (single cached snapshot per game).
    counter_sids = np.broadcast_to(
        agent._counter_sids.squeeze(0).cpu().numpy(),
        (B, agent.cfg.n_counter_slots),
    ).copy()
    active_slot_mask = np.broadcast_to(
        agent._active_slot_mask.squeeze(0).cpu().numpy(),
        (B, agent.cfg.n_counter_slots),
    ).copy()
    char_skill_refs_cached = agent._char_skill_refs.squeeze(0).cpu().numpy()
    char_skill_refs = np.broadcast_to(
        char_skill_refs_cached,
        (B,) + char_skill_refs_cached.shape,
    ).copy()
    hook_types_cached = agent._hook_types_cache.cpu().numpy()
    hook_values_cached = agent._hook_values_cache.cpu().numpy()
    hook_mask_cached = agent._hook_mask.squeeze(0).cpu().numpy()
    hook_types = np.broadcast_to(hook_types_cached, (B,) + hook_types_cached.shape).copy()
    hook_values = np.broadcast_to(hook_values_cached, (B,) + hook_values_cached.shape).copy()
    hook_mask = np.broadcast_to(hook_mask_cached, (B,) + hook_mask_cached.shape).copy()

    return {
        'counter_values': np.stack(counter_values_list, axis=0),
        'meta': np.stack(meta_list, axis=0),
        'card_buckets': np.stack(card_buckets_list, axis=0),
        'enemy_sizes': np.stack(enemy_sizes_list, axis=0),
        'recent_damage': np.stack(recent_damage_list, axis=0),
        'prepare_skill': np.stack(prepare_skill_list, axis=0),
        'modifier_log': np.stack(modifier_log_list, axis=0),
        'action_refs': np.stack(refs_list, axis=0).astype(np.int64),
        'action_payments': np.stack(payments_list, axis=0).astype(np.float32),
        'legal_mask': legal_mask,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'char_skill_refs': char_skill_refs,
        'hook_types': hook_types,
        'hook_values': hook_values,
        'hook_mask': hook_mask,
    }
