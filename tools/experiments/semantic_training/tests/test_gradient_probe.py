"""Gradient geometry distinguishes disconnection from opposing gradients."""

import pytest
import torch

from tools.experiments.semantic_training.gradient_probe import compare_gradients


def test_gradient_geometry_preserves_disconnected_head_and_opposition():
    names = [('base.hook_encoder.weight', None), ('base.heads.q.weight', None)]
    result = compare_gradients(
        names, (torch.tensor([3.0, 4.0]), torch.tensor([2.0])), (torch.tensor([-6.0, -8.0]), None), 0.5
    )
    assert result['hook_encoder']['cosine'] == pytest.approx(-1)
    assert result['hook_encoder']['scaled_auxiliary_norm'] == pytest.approx(5)
    assert result['policy_head']['auxiliary_connected_tensors'] == 0
    assert result['policy_head']['cosine'] is None
    assert result['all']['policy_norm'] == pytest.approx(29**0.5)
