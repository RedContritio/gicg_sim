"""Operand roles must survive encoding instead of collapsing into a multiset."""

import pytest
import torch

from training.core.network.encoder import HookEncoder


@pytest.mark.parametrize('slot', [2, 3, 4])
def test_destination_and_each_operand_are_distinguishable(slot):
    torch.manual_seed(93800)
    enc = HookEncoder(token_dim=16, n_heads=4, n_layers=1, max_ops=2, dropout=0)
    original = torch.tensor([[[[1, 2, 3, 7, 11], [0, 0, 0, 0, 0]]]])
    swapped = original.clone()
    swapped[..., 0, 1], swapped[..., 0, slot] = original[..., 0, slot], original[..., 0, 1]
    batch = torch.cat([original, swapped])
    result = enc(batch, torch.ones(2, 1, dtype=torch.bool))
    assert torch.isfinite(result).all()
    assert (result[0] - result[1]).abs().max() > 1e-3
    target = torch.arange(16, dtype=result.dtype)
    loss = (result[0, 0] - target).square().mean() + (result[1, 0] + target).square().mean()
    loss.backward()
    assert torch.isfinite(enc.operand_projection.weight.grad).all()
    for block in enc.operand_projection.weight.grad.split(16, dim=1):
        assert block.abs().sum() > 0


def test_old_encoder_weights_cannot_silently_load_as_role_aware():
    enc = HookEncoder(token_dim=16, n_heads=4, n_layers=1, max_ops=2, dropout=0)
    old = {k: v for k, v in enc.state_dict().items() if k != 'operand_projection.weight'}
    with pytest.raises(RuntimeError, match='operand_projection.weight'):
        enc.load_state_dict(old)


@pytest.mark.parametrize('values', [(-1, 0), (2048, 2049), (-20, -2)])
def test_numeric_literals_do_not_alias_at_vocabulary_boundaries(values):
    torch.manual_seed(93801)
    enc = HookEncoder(token_dim=16, n_heads=4, n_layers=1, max_ops=1, dropout=0)
    ir = torch.tensor([[[[1, 0, v, 0, 0]]] for v in values])
    result = enc(ir, torch.ones(2, 1, dtype=torch.bool))
    assert torch.isfinite(result).all()
    assert not torch.allclose(result[0], result[1], atol=1e-6, rtol=1e-6)
    (result * torch.arange(16)).sum().backward()
    assert enc.literal_projection[0].weight.grad.abs().sum() > 0


def test_non_literals_do_not_use_numeric_projection():
    torch.manual_seed(93802)
    enc = HookEncoder(token_dim=16, n_heads=4, n_layers=1, max_ops=1, dropout=0)
    ir = torch.tensor([[[[15, 0, 1, 0, 0]]], [[[3, 2, 4, 9, 0]]]])
    mask = torch.ones(2, 1, dtype=torch.bool)
    before = enc(ir, mask).detach()
    with torch.no_grad():
        for p in enc.literal_projection.parameters():
            p.add_(10)
    torch.testing.assert_close(enc(ir, mask), before)


def test_null_reference_and_register_zero_remain_distinct():
    torch.manual_seed(93803)
    enc = HookEncoder(token_dim=16, n_heads=4, n_layers=1, max_ops=1, dropout=0)
    ir = torch.tensor([[[[3, 1, 2, 5, -1]]], [[[3, 1, 2, 5, 0]]]])
    result = enc(ir, torch.ones(2, 1, dtype=torch.bool))
    assert (result[0] - result[1]).abs().max() > 1e-3
