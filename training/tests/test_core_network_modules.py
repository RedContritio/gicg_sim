"""Network module shape smoke tests — encoder + heads + ActorCritic."""

from __future__ import annotations

import torch
import torch.nn as nn

from training.core.network.actor_critic import ActorCritic
from training.core.network.encoder import (
    CardEncoder,
    CounterEncoder,
    CrossAttentionBlock,
    HookEncoder,
)
from training.core.network.heads import (
    AvgPolicyHead,
    DeltaHead,
    PolicyHead,
    QHead,
    ValueHead,
)
from training.core.network.struct_readout import StructReadoutBlock
from training.core.obs_constants import (
    DICE_COLOR_COUNT,
    N_STRUCTURAL,
    OBS_ENEMY_SIZES,
    OBS_HAND_BUCKETS,
    OBS_MAX_CARD_TYPES,
    OBS_META_SIZE,
)


D = 32


def test_hook_encoder_shape():
    enc = HookEncoder(token_dim=D, max_tokens=10)
    B, N, T = 2, 3, 10
    types = torch.randint(0, 100, (B, N, T))
    values = torch.randn(B, N, T)
    mask = torch.ones(B, N, dtype=torch.bool)
    out = enc(types, values, mask)
    assert out.shape == (B, N, D)


def test_counter_encoder_shape():
    enc = CounterEncoder(max_slots=100, embed_dim=D)
    B, S = 2, 8
    values = torch.randn(B, S)
    sids = torch.randint(0, 100, (B, S))
    mask = torch.zeros(B, S, dtype=torch.bool)
    mask[:, :4] = True
    emb, m = enc(values, sids, mask)
    assert emb.shape[0] == B
    assert emb.shape[2] == D


def test_card_encoder_shape():
    enc = CardEncoder(d_model=D)
    B = 2
    buckets = torch.randn(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    enemy = torch.randn(B, OBS_ENEMY_SIZES)
    out = enc(buckets, enemy)
    assert out.shape == (B, D)


def test_struct_readout_shape():
    block = StructReadoutBlock(d_model=D)
    B = 2
    x = torch.randn(B, N_STRUCTURAL)
    assert block(x).shape == (B, D)


def test_policy_head_shape():
    head = PolicyHead(d_model=D)
    B, A = 2, 16
    s = torch.randn(B, D)
    a = torch.randn(B, A, D)
    logits = head(s, a)
    assert logits.shape == (B, A)


def test_value_head_shape():
    head = ValueHead(in_dim=D * 6, d_model=D)
    B = 2
    x = torch.randn(B, D * 6)
    out = head(x)
    assert out.shape == (B,)
    # tanh bounds
    assert (out >= -1).all() and (out <= 1).all()


def test_q_head_shape():
    head = QHead(d_model=D)
    B, A = 2, 8
    s = torch.randn(B, D)
    a = torch.randn(B, A, D)
    assert head(s, a).shape == (B, A)


def test_avg_policy_head_shape():
    head = AvgPolicyHead(d_model=D)
    B, A = 2, 8
    s = torch.randn(B, D)
    a = torch.randn(B, A, D)
    assert head(s, a).shape == (B, A)


def test_delta_head_shape():
    head = DeltaHead(in_dim=D * 6, d_model=D, n_counter_slots=20)
    B = 2
    x = torch.randn(B, D * 6)
    assert head(x).shape == (B, 20)


def test_actor_critic_forward_shape():
    n_counter_slots = 16
    n_hooks = 4
    max_tokens = 8
    max_actions = 6
    d_model = D
    heads = nn.ModuleDict(
        {
            'policy': PolicyHead(d_model=d_model),
            'value': ValueHead(in_dim=d_model * 6, d_model=d_model),
        }
    )
    net = ActorCritic(
        n_counter_slots=n_counter_slots,
        n_hooks=n_hooks,
        max_tokens_per_hook=max_tokens,
        max_actions=max_actions,
        heads=heads,
        d_model=d_model,
        typed_damage=None,
    )
    net.eval()
    B = 2
    counter_values = torch.randn(B, n_counter_slots)
    counter_sids = torch.randint(0, 100, (B, n_counter_slots))
    active_slot_mask = torch.ones(B, n_counter_slots, dtype=torch.bool)
    hook_emb_cached = torch.randn(B, n_hooks, d_model)
    hook_mask = torch.ones(B, n_hooks, dtype=torch.bool)
    card_buckets = torch.randn(B, OBS_HAND_BUCKETS, OBS_MAX_CARD_TYPES)
    enemy_sizes = torch.randn(B, OBS_ENEMY_SIZES)
    meta = torch.randn(B, OBS_META_SIZE)
    action_refs = torch.zeros(B, max_actions, 3, dtype=torch.long)
    action_payments = torch.randn(B, max_actions, DICE_COLOR_COUNT)
    structural_values = torch.randn(B, N_STRUCTURAL)
    char_skill_refs = torch.full((B, 2, 6, 10), -1, dtype=torch.long)

    out = net(
        counter_values,
        counter_sids,
        active_slot_mask,
        hook_emb_cached,
        hook_mask,
        card_buckets,
        enemy_sizes,
        meta,
        action_refs,
        action_payments,
        structural_values,
        char_skill_refs,
    )
    assert out['policy'].shape == (B, max_actions)
    assert out['value'].shape == (B,)


def test_cross_attention_smoke():
    block = CrossAttentionBlock(d_model=D)
    B, Nc, Nh = 2, 5, 4
    c = torch.randn(B, Nc, D)
    h = torch.randn(B, Nh, D)
    cm = torch.ones(B, Nc, dtype=torch.bool)
    hm = torch.ones(B, Nh, dtype=torch.bool)
    out_c, out_h = block(c, h, cm, hm)
    assert out_c.shape == c.shape
    assert out_h.shape == h.shape
