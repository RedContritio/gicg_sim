"""Tests for new generic ActorCritic + make_actor_critic factory.

Covers:
- Factory creates correct head subset per head_kinds
- typed_damage=True/False switches 6/7 pool layout
- Unknown head kind raises ValueError
- Forward with/without typed segments runtime validation
"""

from __future__ import annotations

import pytest
import torch

from training.core.cfg import ObsShape
from training.core.network.actor_critic import (
    HEAD_REGISTRY,
    ActorCritic,
    make_actor_critic,
)
from training.core.network.typed_damage import TypedDamageEncoder
from training.core.obs_constants import (
    DICE_COLOR_COUNT,
    N_STRUCTURAL,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
    OBS_MODIFIER_LOG_FIELD_COUNT,
    OBS_MODIFIER_LOG_K_MOD,
    OBS_RECENT_DAMAGE_EVENTS,
    OBS_RECENT_DAMAGE_FIELD_COUNT,
)


def _shape(d_model: int = 32) -> ObsShape:
    return ObsShape(
        n_counter_slots=16,
        n_hooks=4,
        max_ops_per_hook=8,
        max_actions=6,
        d_model=d_model,
    )


def test_head_registry_complete():
    """All 5 head kinds present in registry."""
    assert set(HEAD_REGISTRY.keys()) == {'policy', 'value', 'q', 'avg_policy', 'delta'}


def test_make_actor_critic_az_heads():
    """AZ uses policy + value + delta, typed_damage on."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'}, use_typed_damage=True)
    assert isinstance(net, ActorCritic)
    assert set(net.heads.keys()) == {'policy', 'value', 'delta'}
    assert net.typed_damage is not None
    assert net._n_pools == 7


def test_make_actor_critic_dmc_q_head():
    """DMC uses single Q head."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'q'}, use_typed_damage=True)
    assert set(net.heads.keys()) == {'q'}
    assert net.typed_damage is not None
    assert net._n_pools == 7


def test_make_actor_critic_no_typed_damage():
    """6-pool layout when typed_damage off."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'policy', 'value'}, use_typed_damage=False)
    assert net.typed_damage is None
    assert net._n_pools == 6


def test_make_actor_critic_unknown_head_raises():
    cfg = _shape()
    with pytest.raises(ValueError, match='unknown head kinds'):
        make_actor_critic(cfg, head_kinds={'policy', 'mystery'}, use_typed_damage=True)


def test_actor_critic_forward_typed_damage_off():
    """Forward without typed_damage segments works in 6-pool mode."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'policy', 'value'}, use_typed_damage=False)
    net.eval()
    B, ncs, nh, ma = 2, cfg.n_counter_slots, cfg.n_hooks, cfg.max_actions

    out = net(
        counter_values=torch.randn(B, ncs),
        counter_sids=torch.randint(0, 100, (B, ncs)),
        active_slot_mask=torch.ones(B, ncs, dtype=torch.bool),
        hook_emb_cached=torch.randn(B, nh, cfg.d_model),
        hook_mask=torch.ones(B, nh, dtype=torch.bool),
        card_buckets=torch.randn(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES),
        enemy_sizes=torch.randn(B, OBS_ENEMY_SIZES),
        meta=torch.randn(B, OBS_META_SIZE),
        action_refs=torch.zeros(B, ma, 3, dtype=torch.long),
        action_payments=torch.randn(B, ma, DICE_COLOR_COUNT),
        structural_values=torch.randn(B, N_STRUCTURAL),
        char_skill_refs=torch.full((B, 2, 6, 10), -1, dtype=torch.long),
    )
    assert out['policy'].shape == (B, ma)
    assert out['value'].shape == (B,)
    assert (out['value'] >= -1).all() and (out['value'] <= 1).all()


def test_actor_critic_forward_typed_damage_on():
    """Forward with typed_damage segments in 7-pool mode."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'}, use_typed_damage=True)
    net.eval()
    B, ncs, nh, ma = 2, cfg.n_counter_slots, cfg.n_hooks, cfg.max_actions

    out = net(
        counter_values=torch.randn(B, ncs),
        counter_sids=torch.randint(0, 100, (B, ncs)),
        active_slot_mask=torch.ones(B, ncs, dtype=torch.bool),
        hook_emb_cached=torch.randn(B, nh, cfg.d_model),
        hook_mask=torch.ones(B, nh, dtype=torch.bool),
        card_buckets=torch.randn(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES),
        enemy_sizes=torch.randn(B, OBS_ENEMY_SIZES),
        meta=torch.randn(B, OBS_META_SIZE),
        action_refs=torch.zeros(B, ma, 3, dtype=torch.long),
        action_payments=torch.randn(B, ma, DICE_COLOR_COUNT),
        structural_values=torch.randn(B, N_STRUCTURAL),
        char_skill_refs=torch.full((B, 2, 6, 10), -1, dtype=torch.long),
        # typed segments: zeros for categorical fields (0 = valid char/element/etc);
        # randn would give out-of-range long indices when typed_damage casts to long.
        recent_damage=torch.zeros(B, OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT),
        prepare_skill=torch.zeros(B, 2, 2, dtype=torch.float32),
        modifier_log=torch.zeros(B, OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT),
    )
    assert out['policy'].shape == (B, ma)
    assert out['value'].shape == (B,)
    assert out['delta'].shape == (B, cfg.n_counter_slots)


def test_actor_critic_typed_damage_mismatch_raises():
    """Construct with typed_damage=None, pass segments → ValueError."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'policy', 'value'}, use_typed_damage=False)
    B, ncs, nh, ma = 1, cfg.n_counter_slots, cfg.n_hooks, cfg.max_actions
    with pytest.raises(ValueError, match='typed_damage segments passed but self.typed_damage is None'):
        net(
            counter_values=torch.randn(B, ncs),
            counter_sids=torch.randint(0, 100, (B, ncs)),
            active_slot_mask=torch.ones(B, ncs, dtype=torch.bool),
            hook_emb_cached=torch.randn(B, nh, cfg.d_model),
            hook_mask=torch.ones(B, nh, dtype=torch.bool),
            card_buckets=torch.randn(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES),
            enemy_sizes=torch.randn(B, OBS_ENEMY_SIZES),
            meta=torch.randn(B, OBS_META_SIZE),
            action_refs=torch.zeros(B, ma, 3, dtype=torch.long),
            action_payments=torch.randn(B, ma, DICE_COLOR_COUNT),
            structural_values=torch.randn(B, N_STRUCTURAL),
            char_skill_refs=torch.full((B, 2, 6, 10), -1, dtype=torch.long),
            recent_damage=torch.randn(B, OBS_RECENT_DAMAGE_EVENTS, OBS_RECENT_DAMAGE_FIELD_COUNT),
            prepare_skill=torch.zeros(B, 2, 2, dtype=torch.float32),
            modifier_log=torch.randn(B, OBS_RECENT_DAMAGE_EVENTS, OBS_MODIFIER_LOG_K_MOD, OBS_MODIFIER_LOG_FIELD_COUNT),
        )


def test_actor_critic_typed_damage_missing_segments_raises():
    """Construct with typed_damage=True, forget segments → ValueError."""
    cfg = _shape()
    net = make_actor_critic(cfg, head_kinds={'policy', 'value'}, use_typed_damage=True)
    B, ncs, nh, ma = 1, cfg.n_counter_slots, cfg.n_hooks, cfg.max_actions
    with pytest.raises(ValueError, match='typed_damage encoder requires'):
        net(
            counter_values=torch.randn(B, ncs),
            counter_sids=torch.randint(0, 100, (B, ncs)),
            active_slot_mask=torch.ones(B, ncs, dtype=torch.bool),
            hook_emb_cached=torch.randn(B, nh, cfg.d_model),
            hook_mask=torch.ones(B, nh, dtype=torch.bool),
            card_buckets=torch.randn(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES),
            enemy_sizes=torch.randn(B, OBS_ENEMY_SIZES),
            meta=torch.randn(B, OBS_META_SIZE),
            action_refs=torch.zeros(B, ma, 3, dtype=torch.long),
            action_payments=torch.randn(B, ma, DICE_COLOR_COUNT),
            structural_values=torch.randn(B, N_STRUCTURAL),
            char_skill_refs=torch.full((B, 2, 6, 10), -1, dtype=torch.long),
        )
