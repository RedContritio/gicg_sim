"""Tests for training/network.py in AZ form: ActorCritic forward
contract, az_losses computation, Agent eval_state / forward_batch /
save-load round-trip. These are architectural smoke tests — they
do not exercise a real game, only random tensors of the right shape.

Game-integrated smoke (encode_static on a real GicgEnv + eval_state
on a real state) lives in the MCTS step's tests once that kernel
lands."""

from __future__ import annotations

import numpy as np
import pytest
import torch

from training.core.cfg import ObsShape
from training.core.network import make_actor_critic
from training.paradigms.az._az_losses import az_losses
from training.core.obs_constants import (
    ACTION_CARD,
    ACTION_END_TURN,
    ACTION_SKILL,
    ACTION_SWITCH,
    DICE_COLOR_COUNT,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
)
from training.paradigms.az.network import Agent, AgentConfig
from training.tests._typed_obs_fixtures import (
    make_modifier_log_padding_torch,
    make_prepare_skill_padding_torch,
    make_recent_damage_padding_torch,
)


def _make_net(*, d_model=16, n_slots=128, n_hooks=8, max_tok=12, max_actions=6):
    """Small ActorCritic suitable for random-input tests."""
    torch.manual_seed(0)
    cfg = ObsShape(
        n_counter_slots=n_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_tok,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=1,
        dropout=0.0,
    )
    return make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'}, use_typed_damage=True)


def _random_batch(*, B=2, d_model=16, n_slots=128, n_hooks=8, max_actions=6, n_legal_per_row=3, seed=0):
    """Build a plausible random batch of inputs for ActorCritic.forward.
    legal_mask marks the first n_legal_per_row columns as legal;
    pi_target is a uniform distribution over those legal slots."""
    rng = np.random.RandomState(seed)

    counter_values = torch.zeros(B, n_slots)
    # Sprinkle a handful of non-zero counter values so the sparse
    # sort path has content to sort.
    for b in range(B):
        for i in rng.choice(n_slots, size=5, replace=False):
            counter_values[b, i] = float(rng.randint(1, 10))
    counter_sids = torch.randint(0, n_slots, (B, n_slots), dtype=torch.long)
    active_slot_mask = torch.ones(B, n_slots, dtype=torch.bool)
    hook_emb = torch.randn(B, n_hooks, d_model)
    hook_mask = torch.ones(B, n_hooks, dtype=torch.bool)
    card_buckets = torch.zeros(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    enemy_sizes = torch.zeros(B, OBS_ENEMY_SIZES)
    meta = torch.zeros(B, OBS_META_SIZE)

    refs = torch.full((B, max_actions, 3), -1, dtype=torch.long)
    refs[:, :, 0] = ACTION_END_TURN  # padding = end turn, hook_idx=-1
    for b in range(B):
        for a in range(n_legal_per_row):
            if a == 0:
                refs[b, a] = torch.tensor([ACTION_SKILL, 0, -1])
            elif a == 1:
                refs[b, a] = torch.tensor([ACTION_CARD, 1, -1])
            else:
                refs[b, a] = torch.tensor([ACTION_SWITCH, -1, 1])

    payments = torch.zeros(B, max_actions, DICE_COLOR_COUNT)
    payments[:, 0, 0] = 3.0
    payments[:, 1, 2] = 1.0
    payments[:, 1, 7] = 2.0

    legal_mask = torch.zeros(B, max_actions, dtype=torch.bool)
    legal_mask[:, :n_legal_per_row] = True

    pi_target = torch.zeros(B, max_actions)
    pi_target[:, :n_legal_per_row] = 1.0 / n_legal_per_row

    z_target = torch.tensor([1.0, -1.0][:B], dtype=torch.float32)
    if B > 2:
        z_target = torch.cat([z_target, torch.zeros(B - 2)])

    structural_values = torch.zeros(B, 66)

    # char_skill_refs: shape (B, 2, 6, 10). Leave as -1 (no skills) by
    # default — forward must handle the all-empty case gracefully.
    char_skill_refs = torch.full((B, 2, 6, 10), -1, dtype=torch.long)

    return {
        'counter_values': counter_values,
        'counter_sids': counter_sids,
        'active_slot_mask': active_slot_mask,
        'hook_emb': hook_emb,
        'hook_mask': hook_mask,
        'card_buckets': card_buckets,
        'enemy_sizes': enemy_sizes,
        'meta': meta,
        'action_refs': refs,
        'action_payments': payments,
        'structural_values': structural_values,
        'char_skill_refs': char_skill_refs,
        # ADR-0019 §B.2/§B.3c typed obs segments — Round-6 S-3 sentinel
        'recent_damage': make_recent_damage_padding_torch(B=B),
        'prepare_skill': make_prepare_skill_padding_torch(B=B),
        'modifier_log': make_modifier_log_padding_torch(B=B),
        'legal_mask': legal_mask,
        'pi_target': pi_target,
        'z_target': z_target,
    }


class TestActorCriticForward:
    def test_shape_and_value_range(self):
        net = _make_net()
        batch = _random_batch(B=2, max_actions=6, n_legal_per_row=3)
        out = net(
            batch['counter_values'],
            batch['counter_sids'],
            batch['active_slot_mask'],
            batch['hook_emb'],
            batch['hook_mask'],
            batch['card_buckets'],
            batch['enemy_sizes'],
            batch['meta'],
            batch['action_refs'],
            batch['action_payments'],
            batch['structural_values'],
            batch['char_skill_refs'],
            batch['recent_damage'],
            batch['prepare_skill'],
            batch['modifier_log'],
        )
        logits, value = out['policy'], out['value']
        assert logits.shape == (2, 6)
        assert value.shape == (2,)
        # tanh bound
        assert (value >= -1.0 - 1e-6).all() and (value <= 1.0 + 1e-6).all()

    def test_logits_are_raw_not_masked(self):
        """Illegal slots should have finite logits — masking happens in
        the loss / MCTS side, not inside forward."""
        net = _make_net()
        batch = _random_batch(B=1, max_actions=6, n_legal_per_row=2)
        with torch.no_grad():
            out = net(
                batch['counter_values'],
                batch['counter_sids'],
                batch['active_slot_mask'],
                batch['hook_emb'],
                batch['hook_mask'],
                batch['card_buckets'],
                batch['enemy_sizes'],
                batch['meta'],
                batch['action_refs'],
                batch['action_payments'],
                batch['structural_values'],
                batch['char_skill_refs'],
                batch['recent_damage'],
                batch['prepare_skill'],
                batch['modifier_log'],
            )
            logits = out['policy']
        # Illegal slots (index >= n_legal) should NOT be the very-negative
        # -1e9 sentinel — they're just whatever the pointer-net produces.
        assert (logits[0, 2:] > -1e8).all()

    def test_different_payments_differ(self):
        """Two otherwise identical skill rows with different dice payments
        must produce different logits — guards dice_combo_proj."""
        torch.manual_seed(42)
        net = _make_net()
        B = 1
        counter_values = torch.zeros(B, 64)
        counter_sids = torch.zeros(B, 64, dtype=torch.long)
        hook_emb = torch.randn(B, 8, 16)
        hook_mask = torch.ones(B, 8, dtype=torch.bool)
        card_buckets = torch.zeros(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
        enemy_sizes = torch.zeros(B, OBS_ENEMY_SIZES)
        meta = torch.zeros(B, OBS_META_SIZE)

        refs = torch.full((B, 6, 3), -1, dtype=torch.long)
        refs[:, :, 0] = ACTION_END_TURN
        refs[0, 0] = torch.tensor([ACTION_SKILL, 0, -1])
        refs[0, 1] = torch.tensor([ACTION_SKILL, 0, -1])

        payments = torch.zeros(B, 6, DICE_COLOR_COUNT)
        payments[0, 0] = torch.tensor([3, 0, 0, 0, 0, 0, 0, 0], dtype=torch.float32)
        payments[0, 1] = torch.tensor([1, 0, 0, 0, 0, 0, 0, 2], dtype=torch.float32)

        with torch.no_grad():
            active_slot_mask = torch.ones(B, 64, dtype=torch.bool)
            structural_values = torch.zeros(B, 66)
            char_skill_refs = torch.full((B, 2, 6, 10), -1, dtype=torch.long)
            # Round-6 S-3 sentinel
            recent_damage = make_recent_damage_padding_torch(B=B)
            prepare_skill = make_prepare_skill_padding_torch(B=B)
            modifier_log = make_modifier_log_padding_torch(B=B)
            out = net(
                counter_values,
                counter_sids,
                active_slot_mask,
                hook_emb,
                hook_mask,
                card_buckets,
                enemy_sizes,
                meta,
                refs,
                payments,
                structural_values,
                char_skill_refs,
                recent_damage,
                prepare_skill,
                modifier_log,
            )
            logits = out['policy']
        assert not torch.allclose(logits[0, 0], logits[0, 1], atol=1e-6)
