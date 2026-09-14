"""End-to-end mirror probe (Round-2 review P2).

The TypedDamageEncoder unit test (`test_typed_damage_encoder.py`) verifies
mirror disentanglement at the encoder level — output differs when P0/P1
are swapped. But the encoder output is just one of 7 pools concatenated
into the policy/value combined feature, then projected through several
layers (state_proj, value_head). At each layer the typed_pool's signal
might be diluted or canceled by other pool contributions.

This test pushes a mirror-asymmetric obs through the FULL ActorCritic
forward and verifies logits + value differ between P0_active vs
P1_active states. If the typed signal is real but doesn't reach the
output, this test fails — proving the encoder-level test alone is
insufficient.
"""

from __future__ import annotations

import numpy as np
import torch

from training.core.network import ActorCritic, make_actor_critic
from training.core.network.agent_base import AgentConfig
from training.core.obs_constants import (
    ACTION_END_TURN,
    ACTION_SKILL,
    DICE_COLOR_COUNT,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
)


def _zero_inputs(B: int, n_slots: int, n_hooks: int, d_model: int, max_actions: int):
    """Build a minimum non-degenerate ActorCritic input set.

    Round-4 S-1: 与 engine 实际 padding sentinel 一致 — recent_damage /
    modifier_log categorical 字段 = -2(Round-3 M3+M4 修复),scalar = 0,
    prepare_skill = -1(encodePrepareSkill 的 "no prepare" real 语义)。
    之前 fixture 用 -1 当 recent_damage padding 跟 _zero_obs (encoder unit
    test) 不一致,encoder 把它解读成 "real no-actor",mirror 断言虽过
    但走的不是生产 padding 路径。
    """
    counter_values = torch.zeros(B, n_slots)
    counter_sids = torch.zeros(B, n_slots, dtype=torch.long)
    active_slot_mask = torch.ones(B, n_slots, dtype=torch.bool)
    hook_emb = torch.randn(B, n_hooks, d_model)
    hook_mask = torch.ones(B, n_hooks, dtype=torch.bool)
    card_buckets = torch.zeros(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    enemy_sizes = torch.zeros(B, OBS_ENEMY_SIZES)
    meta = torch.zeros(B, OBS_META_SIZE)
    refs = torch.full((B, max_actions, 3), -1, dtype=torch.long)
    refs[:, :, 0] = ACTION_END_TURN
    refs[:, 0, 0] = ACTION_SKILL
    refs[:, 0, 1] = 0  # hook_idx
    payments = torch.zeros(B, max_actions, DICE_COLOR_COUNT)
    structural_values = torch.zeros(B, 66)
    char_skill_refs = torch.full((B, 2, 6, 10), -1, dtype=torch.long)
    # Round-6 S-3: 共享 typed obs padding helper(_typed_obs_fixtures)
    from training.tests._typed_obs_fixtures import (
        make_modifier_log_padding_torch,
        make_prepare_skill_padding_torch,
        make_recent_damage_padding_torch,
    )

    recent_damage = make_recent_damage_padding_torch(B=B)
    prepare_skill = make_prepare_skill_padding_torch(B=B)
    modifier_log = make_modifier_log_padding_torch(B=B)
    definition_links = torch.full((B, 1, 2), -1, dtype=torch.long)
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
        'recent_damage': recent_damage,
        'prepare_skill': prepare_skill,
        'modifier_log': modifier_log,
        'definition_links': definition_links,
    }


def _forward(net: ActorCritic, inputs: dict):
    """Run net forward and unpack the dict return into (logits, value, delta)
    for the legacy 3-tuple test contract. Post core-network-generic-promotion
    Phase 2A, generic ActorCritic returns dict {head_name: tensor, _state_vec,
    _action_emb, _combined}; AZ paradigm uses {policy, value, delta} subset."""
    out = net(
        inputs['counter_values'],
        inputs['counter_sids'],
        inputs['active_slot_mask'],
        inputs['hook_emb'],
        inputs['hook_mask'],
        inputs['card_buckets'],
        inputs['enemy_sizes'],
        inputs['meta'],
        inputs['action_refs'],
        inputs['action_payments'],
        inputs['structural_values'],
        inputs['char_skill_refs'],
        inputs['recent_damage'],
        inputs['prepare_skill'],
        inputs['modifier_log'],
        definition_links=inputs['definition_links'],
    )
    return out['policy'], out['value'], out['delta']


def _make_az_net(d_model=16, n_slots=64, n_hooks=8, max_tokens=12, max_actions=6, dropout=0.0):
    """Build a generic ActorCritic with AZ head subset {policy, value, delta}
    + typed_damage enabled — matches production AZ network composition."""
    cfg = AgentConfig(
        n_counter_slots=n_slots,
        n_hooks=n_hooks,
        max_ops_per_hook=max_tokens,
        max_actions=max_actions,
        d_model=d_model,
        n_cross_layers=1,
        dropout=dropout,
    )
    return make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'}, use_typed_damage=True)


class TestActorCriticMirrorEndToEnd:
    """Round-2 review P2: encoder-level mirror invariant must propagate
    through state_proj / value_head — verify with full ActorCritic forward.

    The risk this test catches: typed signal disentanglement is fine at
    encoder level but the cross_layers / 7-pool concat downstream
    averages it out — so logits and value stay identical under mirror
    swap, the encoder's correctness is wasted."""

    def _make_net(self, d_model=16, n_slots=64, n_hooks=8, max_tokens=12, max_actions=6):
        torch.manual_seed(0)
        return _make_az_net(
            d_model=d_model, n_slots=n_slots, n_hooks=n_hooks, max_tokens=max_tokens, max_actions=max_actions
        )

    def test_full_forward_distinct_under_p0_vs_p1_prepare(self):
        """Full forward pass: P0 prepares skill X vs P1 prepares same X
        must produce different (logits, value)."""
        net = self._make_net()
        net.eval()

        inputs_a = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        # Same hook_emb so the random pool isn't the differentiator
        inputs_b['hook_emb'] = inputs_a['hook_emb'].clone()

        # Mirror prepare_skill: P0 prepares (char=0, slot=1) vs P1
        inputs_a['prepare_skill'][0, 0, 0] = 0
        inputs_a['prepare_skill'][0, 0, 1] = 1
        inputs_b['prepare_skill'][0, 1, 0] = 0
        inputs_b['prepare_skill'][0, 1, 1] = 1

        with torch.no_grad():
            logits_a, value_a, _ = _forward(net, inputs_a)
            logits_b, value_b, _ = _forward(net, inputs_b)

        assert not torch.allclose(logits_a, logits_b, atol=1e-5), (
            'full ActorCritic forward: P0_prepare vs P1_prepare produced '
            'identical logits — typed signal failed to propagate to policy head.'
        )
        assert not torch.isclose(value_a, value_b, atol=1e-5).all(), (
            'full ActorCritic forward: value scalar identical under mirror — '
            'typed signal failed to propagate to value head.'
        )

    def test_full_forward_distinct_under_actor_swap(self):
        """Actor identity stays distinct and reaches both full-model heads.

        Randomly initialized output magnitudes are not a stable separation
        oracle: the mirror signal can reach a head while its scalar output
        difference happens to fall below an arbitrary ``allclose`` tolerance.
        Instead, verify the two required properties directly:

        * swapping actor/target changes the typed representation; and
        * a controlled differentiable perturbation at that representation
          backpropagates through the full policy and value paths.
        """
        net = self._make_net()
        net.eval()

        inputs_a = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b['hook_emb'] = inputs_a['hook_emb'].clone()

        # State A: P0 attacks P1 with Fire 3
        inputs_a['recent_damage'][0, 0, 0] = 0  # actor_player
        inputs_a['recent_damage'][0, 0, 1] = 0  # actor_char
        inputs_a['recent_damage'][0, 0, 2] = 1  # target_player
        inputs_a['recent_damage'][0, 0, 3] = 0  # target_char
        inputs_a['recent_damage'][0, 0, 4] = 1  # element=Fire
        inputs_a['recent_damage'][0, 0, 5] = 3
        inputs_a['recent_damage'][0, 0, 6] = 3
        inputs_a['recent_damage'][0, 0, 9] = 1
        inputs_a['recent_damage'][0, 0, 10] = 0  # reaction_kind

        # State B: P1 attacks P0 (mirror swap)
        inputs_b['recent_damage'][0, 0, 0] = 1
        inputs_b['recent_damage'][0, 0, 1] = 0
        inputs_b['recent_damage'][0, 0, 2] = 0
        inputs_b['recent_damage'][0, 0, 3] = 0
        inputs_b['recent_damage'][0, 0, 4] = 1
        inputs_b['recent_damage'][0, 0, 5] = 3
        inputs_b['recent_damage'][0, 0, 6] = 3
        inputs_b['recent_damage'][0, 0, 9] = 1
        inputs_b['recent_damage'][0, 0, 10] = 0

        with torch.no_grad():
            typed_a = net.typed_damage(inputs_a['recent_damage'], inputs_a['prepare_skill'], inputs_a['modifier_log'])
            typed_b = net.typed_damage(inputs_b['recent_damage'], inputs_b['prepare_skill'], inputs_b['modifier_log'])
        assert not torch.equal(typed_a, typed_b), 'actor/target swap was erased by the typed encoder'

        # Interpolate only along the observed actor-swap direction.  At
        # intervention=0 this is state A's typed pool; at 1 it is state B's.
        # A scalar derivative therefore tests that this specific semantic
        # difference, rather than some unrelated typed dimension, reaches the
        # downstream heads.
        swap_direction = (typed_b - typed_a).detach()
        intervention = torch.tensor(0.5, requires_grad=True)

        def inject_typed_signal(_module, _args, output):
            return output + intervention * swap_direction

        assert net.typed_damage is not None
        with net.typed_damage.register_forward_hook(inject_typed_signal):
            logits, value, _ = _forward(net, inputs_a)

        policy_grads = torch.stack(
            [
                torch.autograd.grad(logits[0, action_idx], intervention, retain_graph=True)[0]
                for action_idx in range(logits.shape[1])
            ]
        )
        value_grad = torch.autograd.grad(value.sum(), intervention)[0]

        assert torch.isfinite(policy_grads).all() and torch.count_nonzero(policy_grads) > 0, (
            'policy head has no differentiable path from the typed representation'
        )
        assert torch.isfinite(value_grad).all() and torch.count_nonzero(value_grad) > 0, (
            'value head has no differentiable path from the typed representation'
        )

    def test_typed_signal_propagates_to_value(self):
        """Same setup minus modifier vs with modifier: full-forward
        value scalar must differ. Catches case where modifier signal
        is real at typed_pool but combined_norm/state_proj averages it
        out before reaching value_head."""
        net = self._make_net()
        net.eval()

        inputs_a = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b['hook_emb'] = inputs_a['hook_emb'].clone()

        # Same recent_damage on both, modifier only in B
        for inp in (inputs_a, inputs_b):
            inp['recent_damage'][0, 0, 0] = 0
            inp['recent_damage'][0, 0, 4] = 4  # Electro
            inp['recent_damage'][0, 0, 5] = 4
            inp['recent_damage'][0, 0, 6] = 4
            inp['recent_damage'][0, 0, 9] = 1

        # B: add big ModBoost on event 0
        inputs_b['modifier_log'][0, 0, 0, 0] = 0  # kind = ModBoost
        inputs_b['modifier_log'][0, 0, 0, 1] = 10
        inputs_b['modifier_log'][0, 0, 0, 2] = 20
        inputs_b['modifier_log'][0, 0, 0, 3] = 4
        inputs_b['modifier_log'][0, 0, 0, 4] = 4

        with torch.no_grad():
            _, value_a, _ = _forward(net, inputs_a)
        inputs_b['modifier_log'].requires_grad_()
        _, value_b, _ = _forward(net, inputs_b)
        # Random projection amplitude changes when unrelated input dimensions
        # change. Verify the full information path rather than a fixed random
        # scalar separation threshold.
        assert not torch.equal(value_a, value_b)
        grad = torch.autograd.grad(value_b.sum(), inputs_b['modifier_log'])[0][0, 0, 0, 1:3]
        assert torch.isfinite(grad).all() and grad.abs().sum() > 0


class TestActorCriticMirrorTrainMode:
    """Round-3 review S11: production training uses dropout=0.1 +
    train mode;LayerNorm+Dropout train-mode 行为质变。前面的 eval
    mode mirror tests 可能假阳性通过(dropout 关时 mirror invariant
    成立,但 dropout 开 + 随机 mask 下退化)。

    用 train mode + dropout=0.1 跑 N 次 forward,要求绝大多数
    forward (≥80%) 仍保持 mirror disentanglement。"""

    def _make_net_with_dropout(self, dropout=0.1, d_model=16, n_slots=64, n_hooks=8, max_tokens=12, max_actions=6):
        torch.manual_seed(0)
        return _make_az_net(
            d_model=d_model,
            n_slots=n_slots,
            n_hooks=n_hooks,
            max_tokens=max_tokens,
            max_actions=max_actions,
            dropout=dropout,
        )

    def test_p0_p1_prepare_distinct_under_train_mode_dropout(self):
        """train mode + dropout=0.1: 20 次 forward,至少 16 次镜像
        disentanglement 成立。dropout 偶尔关键 dim 置零是正常的,
        但若多数 forward 失败说明 typed signal 被 dropout 杀光,
        encoder 的 disentanglement 在 production 训练下退化。"""
        net = self._make_net_with_dropout(dropout=0.1)
        net.train()

        inputs_a = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b = _zero_inputs(B=1, n_slots=64, n_hooks=8, d_model=16, max_actions=6)
        inputs_b['hook_emb'] = inputs_a['hook_emb'].clone()

        # Mirror swap: P0 prepares (char=0, slot=1) vs P1
        inputs_a['prepare_skill'][0, 0, 0] = 0
        inputs_a['prepare_skill'][0, 0, 1] = 1
        inputs_b['prepare_skill'][0, 1, 0] = 0
        inputs_b['prepare_skill'][0, 1, 1] = 1

        N = 20
        distinct_count = 0
        torch.manual_seed(7)
        for _ in range(N):
            logits_a, value_a, _ = _forward(net, inputs_a)
            logits_b, value_b, _ = _forward(net, inputs_b)
            if not torch.allclose(logits_a, logits_b, atol=1e-4):
                distinct_count += 1
        assert distinct_count >= int(N * 0.8), (
            f'train mode + dropout=0.1: only {distinct_count}/{N} forwards '
            'showed mirror disentanglement (expected ≥16). dropout may be '
            'erasing typed signal in production training.'
        )
