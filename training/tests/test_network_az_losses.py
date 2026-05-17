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

from training.core.cfg.shape import ObsShape
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
from training.tests._typed_obs_fixtures import (
    make_modifier_log_padding_torch,
    make_prepare_skill_padding_torch,
    make_recent_damage_padding_torch,
)


def _make_net(*, d_model=16, n_slots=128, n_hooks=8, max_tok=12, max_actions=6):
    """Small ActorCritic suitable for random-input tests.

    Built via the generic make_actor_critic factory with AZ head subset
    (policy + value + delta) and typed_damage on (ADR-0019 §B.3a).
    """
    torch.manual_seed(0)
    cfg = ObsShape(
        n_counter_slots=n_slots,
        n_hooks=n_hooks,
        max_tokens_per_hook=max_tok,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=1,
        dropout=0.0,
    )
    return make_actor_critic(
        cfg,
        head_kinds={'policy', 'value', 'delta'},
        use_typed_damage=True,
    )


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


class TestAZLosses:
    def test_finite_components(self):
        net = _make_net()
        batch = _random_batch(B=4, n_legal_per_row=3)
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
        losses = az_losses(
            logits,
            value,
            batch['legal_mask'],
            batch['pi_target'],
            batch['z_target'],
            model=net,
            l2_coef=1e-4,
        )
        for k in ('total', 'value', 'policy', 'l2'):
            assert k in losses
            assert torch.isfinite(losses[k]).all(), f'{k} is not finite'
        assert losses['l2'].item() > 0
        # policy loss is CE against a uniform distribution → must be positive
        assert losses['policy'].item() > 0

    def test_pi_target_illegal_mass_raises(self):
        """Contract: pi_target must be exactly 0 on illegal slots.
        Non-zero mass there is a caller bug and must raise, not be
        absorbed."""
        net = _make_net()
        batch = _random_batch(B=2, n_legal_per_row=3, max_actions=6)
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
        bad_pi = batch['pi_target'].clone()
        bad_pi[0, 5] = 0.01  # pour mass onto an illegal slot
        with pytest.raises(ValueError, match='illegal slots'):
            az_losses(
                logits,
                value,
                batch['legal_mask'],
                bad_pi,
                batch['z_target'],
            )

    def test_illegal_slots_dont_contribute_to_policy(self):
        """pi_target is zero on illegal slots, so adding arbitrary
        logits to those slots must not change policy_loss."""
        net = _make_net()
        batch = _random_batch(B=2, n_legal_per_row=3, max_actions=6)
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
        loss_a = az_losses(
            logits,
            value,
            batch['legal_mask'],
            batch['pi_target'],
            batch['z_target'],
        )
        # Blast the illegal columns with huge noise — legal mask should
        # absorb them via masked_fill.
        logits_noisy = logits.clone()
        logits_noisy[:, 3:] += 100.0
        loss_b = az_losses(
            logits_noisy,
            value,
            batch['legal_mask'],
            batch['pi_target'],
            batch['z_target'],
        )
        # Policy and value components identical (logits_noisy only
        # changes the illegal slots, which are mask_filled in the loss).
        assert torch.isclose(loss_a['policy'], loss_b['policy'], atol=1e-5)
        assert torch.isclose(loss_a['value'], loss_b['value'], atol=1e-5)

    def test_gradient_reaches_trunk(self):
        """backward() on total loss must populate grads on counter
        encoder / card encoder / cross-attention — i.e. the trunk,
        not just the heads."""
        net = _make_net()
        batch = _random_batch(B=2, n_legal_per_row=3)
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
        losses = az_losses(
            logits,
            value,
            batch['legal_mask'],
            batch['pi_target'],
            batch['z_target'],
            model=net,
            l2_coef=1e-4,
        )
        losses['total'].backward()

        # Spot-check trunk layers have non-None + non-zero grads
        trunk_params = [
            net.counter_encoder.value_proj.weight,
            net.card_encoder.count_proj.weight,
            net.cross_layers[0].counter_to_hook.in_proj_weight,
            net.state_proj[0].weight,
            net.heads['value'].head[0].weight,
            net.dice_combo_proj[0].weight,
        ]
        for p in trunk_params:
            assert p.grad is not None
            assert torch.isfinite(p.grad).all()
            assert p.grad.abs().sum().item() > 0

    def test_l2_requires_model_when_enabled(self):
        net = _make_net()
        batch = _random_batch(B=1, n_legal_per_row=2)
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
        with pytest.raises(ValueError, match='l2_coef > 0 requires model'):
            az_losses(
                logits,
                value,
                batch['legal_mask'],
                batch['pi_target'],
                batch['z_target'],
                l2_coef=1e-4,  # model missing
            )
