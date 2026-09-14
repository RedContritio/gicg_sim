"""Semantic order, padding, transfer and replay regression tests."""

import numpy as np
import pytest
import torch
from torch import nn

from training.core.network.adaptation import load_for_adaptation
from training.core.network.buffs import BuffEncoder
from training.core.network.encoder import HookEncoder
from training.core.rule_learning import RuleCostProbe, mixed_indices, split_rule_groups


def rows():
    return torch.tensor(
        [[[1, 0, -1, 1, -1, 3, 0, 0, 1, 0, 0, 0, 0, -1, -1, -1], [1, 0, 0, 2, 1, 0, 1, 1, 1, 0, 1, 0, 0, -1, -1, -1]]],
        dtype=torch.float32,
    )


def test_order_is_semantic_but_hook_slot_numbers_are_not():
    torch.manual_seed(12)
    enc = BuffEncoder(16).eval()
    hooks = torch.randn(1, 2, 16)
    original = rows()
    a = enc(original, hooks)
    swapped = original.clone()
    swapped[:, :, 6] = 1 - swapped[:, :, 6]
    assert not torch.allclose(a, enc(swapped, hooks))
    remapped = original.clone()
    remapped[:, :, 7] = 1 - remapped[:, :, 7]
    torch.testing.assert_close(a, enc(remapped, hooks.flip(1)))
    padded = torch.cat((original, torch.zeros(1, 5, 16)), dim=1)
    torch.testing.assert_close(a, enc(padded, hooks))
    assert torch.equal(enc(torch.zeros_like(padded), hooks), torch.zeros(1, 16))
    with pytest.raises(ValueError, match='missing rule'):
        broken = original.clone()
        broken[0, 0, 7] = 3
        enc(broken, hooks)


def test_cost_probe_backpropagates_to_shared_rule_and_buff_encoders():
    torch.manual_seed(5)
    hook = HookEncoder(token_dim=16, max_ops=2, dropout=0)
    buff = BuffEncoder(16)
    probe = RuleCostProbe(hook, buff, 16)
    ir = torch.tensor([[[[1, 1, 2, 0, 0], [0, 0, 0, 0, 0]], [[1, 1, 3, 0, 0], [0, 0, 0, 0, 0]]]])
    mask = torch.ones(1, 2, dtype=torch.bool)
    ref = torch.tensor([[0, 0, 0]])
    optimizer = torch.optim.Adam(probe.parameters(), lr=0.001)
    before = (probe(ir, mask, rows(), ref) - 2).square().mean()
    before.backward()
    assert hook.operand_embed.weight.grad.abs().sum() > 0
    assert buff.order.weight.grad.abs().sum() > 0
    optimizer.step()
    after = (probe(ir, mask, rows(), ref) - 2).square().mean()
    assert after < before


def test_adaptation_preserves_old_weights_and_rejects_unrelated_drift_atomically():
    model = nn.ModuleDict({'body': nn.Linear(3, 4), 'buff_encoder': BuffEncoder(4)})
    old = {k: torch.full_like(v, 0.2) for k, v in model.state_dict().items() if not k.startswith('buff_encoder.')}
    with pytest.raises(ValueError, match='missing'):
        load_for_adaptation(model, old)
    old = {k: v.clone() for k, v in model.state_dict().items()}
    before = {k: v.clone() for k, v in model.state_dict().items()}
    bad = dict(old, **{'body.weight': torch.zeros(4, 7)})
    with pytest.raises(ValueError, match='shape'):
        load_for_adaptation(model, bad)
    for k, v in model.state_dict().items():
        torch.testing.assert_close(v, before[k])


def test_adaptation_expands_only_primitive_vocab_rows():
    model = nn.ModuleDict({'operand_embed': nn.Embedding(5, 4)})
    new_rows = model['operand_embed'].weight[3:].detach().clone()
    load_for_adaptation(model, {'operand_embed.weight': torch.ones(3, 4)})
    torch.testing.assert_close(model['operand_embed'].weight[:3], torch.ones(3, 4))
    torch.testing.assert_close(model['operand_embed'].weight[3:], new_rows)


def test_replay_mix_and_rule_group_holdout():
    pairs = mixed_indices(4, 5, 10, 0.3, np.random.default_rng(0))
    assert sum(source for source, _ in pairs) == 3
    train, test = split_rule_groups(['old', 'new', 'old', 'held'], {'held'})
    assert train.tolist() == [0, 1, 2] and test.tolist() == [3]
    with pytest.raises(ValueError):
        mixed_indices(0, 5, 10, 0.3, np.random.default_rng(0))


def test_summon_zone_is_visible_and_old_buff_weights_can_adapt():
    torch.manual_seed(31)
    module = nn.ModuleDict({'buff_encoder': BuffEncoder(16)})
    hooks = torch.randn(1, 2, 16)
    original = rows()
    changed = original.clone()
    changed[:, 0, 11] = 1
    assert not torch.allclose(module['buff_encoder'](original, hooks), module['buff_encoder'](changed, hooks))
    old = {k: v.clone() for k, v in module.state_dict().items()}
    name = 'buff_encoder.state.weight'
    old[name] = old[name][:, :5].clone()
    with pytest.raises(ValueError, match='shape'):
        load_for_adaptation(module, old)


def test_old_public_meta_projection_adapts_without_changing_old_predictions():
    from training.core.obs_constants import OBS_META_SIZE

    assert OBS_META_SIZE == 19
    model = nn.ModuleDict({'meta_proj': nn.Linear(OBS_META_SIZE, 8)})
    old = {'meta_proj.weight': torch.randn(8, 3), 'meta_proj.bias': torch.randn(8)}
    with pytest.raises(ValueError, match='shape'):
        load_for_adaptation(model, old)


def test_typed_entity_bindings_and_absent_targets():
    torch.manual_seed(19)
    source = nn.Embedding(2000, 16)
    enc = BuffEncoder(16, source).eval()
    assert enc.source is source
    hooks = torch.randn(1, 2, 16, requires_grad=True)
    original = rows()[:, :1].clone()
    original[..., 12:] = torch.tensor([3, 10, -1, -1])
    baseline = enc(original, hooks)
    for field, value in [(12, 4), (13, 11), (14, 1), (15, 2), (7, 1)]:
        changed = original.clone()
        changed[..., field] = value
        assert not torch.allclose(baseline, enc(changed, hooks))
    empty = original.clone()
    empty[..., 7] = -1
    empty[..., 3] = 0
    assert torch.isfinite(enc(empty, hooks)).all()
    assert not torch.allclose(baseline, enc(empty, hooks))
    baseline.square().sum().backward()
    assert source.weight.grad[10].abs().sum() > 0
    assert hooks.grad.abs().sum() > 0


def test_suspended_program_locals_and_unordered_rule_bindings():
    torch.manual_seed(47)
    enc = BuffEncoder(16).eval()
    hooks = torch.randn(1, 2, 16, requires_grad=True)
    frame = torch.tensor([[[1, 0, 0, 1, 1, 0, 0, 0, 0, 0, 0, 0, 5, -1, -1, -1]]], dtype=torch.float32)
    baseline = enc(frame, hooks)
    for field, value in [(3, 0), (4, 2), (5, 1), (7, 1), (8, 2), (9, 1), (10, 1)]:
        changed = frame.clone()
        changed[..., field] = value
        assert not torch.equal(baseline, enc(changed, hooks)), field
    binding = frame.clone()
    binding[..., 12] = 6
    binding[..., 7] = 1
    combined = torch.cat([frame, binding], dim=1)
    result = enc(combined, hooks)
    assert not torch.equal(baseline, result)
    torch.testing.assert_close(result, enc(combined.flip(1), hooks))
    remapped = combined.clone()
    remapped[..., 7] = 1 - remapped[..., 7]
    torch.testing.assert_close(result, enc(remapped, hooks.flip(1)))
    result.square().sum().backward()
    assert hooks.grad.abs().sum() > 0
    assert enc.kind.weight.grad[5:7].abs().sum(dim=1).gt(0).all()
    frame[..., 7] = -1  # incomplete bridge can have no public rule reference
    frame[..., 3] = 0
    assert torch.isfinite(enc(frame, hooks)).all()


def test_public_continuation_cause_is_learnable_without_raw_identity():
    torch.manual_seed(61)
    enc = BuffEncoder(16).eval()
    hooks = torch.randn(1, 2, 16, requires_grad=True)
    # Waiting-for-switch row plus public cause row: cause kind=2 (card),
    # trigger=3 (public origin), value=0 (remaining program incomplete).
    rows = torch.tensor(
        [
            [
                [1, 0, -1, 0, 0, 0, 0, -1, 2, 0, 1, 0, 5, -1, -1, -1],
                [1, 1, 0, 0, 2, 0, 0, 0, 3, 0, 0, 0, 5, -1, -1, -1],
            ]
        ],
        dtype=torch.float32,
    )
    first = enc(rows, hooks)
    other = rows.clone()
    other[0, 1, 7] = 1
    assert not torch.equal(first, enc(other, hooks))
    torch.testing.assert_close(first, enc(other, hooks.flip(1)))
    first.square().sum().backward()
    assert hooks.grad[0, 0].abs().sum() > 0
