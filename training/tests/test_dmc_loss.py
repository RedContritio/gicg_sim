"""Contract tests for training/paradigms/dmc/loss.py — DMC MSE loss numerics + raises."""

from __future__ import annotations

import pytest
import torch

from training.paradigms.dmc.loss import dmc_mse_loss


def test_dmc_mse_zero_when_logit_equals_return():
    """Selected-action logit == G → loss = 0."""
    logits = torch.tensor([[1.0, 0.0, 0.0], [-1.0, 0.0, 0.0]])
    action_idx = torch.tensor([0, 0])
    returns = torch.tensor([1.0, -1.0])
    loss = dmc_mse_loss(logits, action_idx, returns)
    assert loss.item() == pytest.approx(0.0, abs=1e-6)


def test_dmc_mse_mean_squared_error_correct():
    """L = mean((logit[a] - G)^2). 2 samples: (0-1)^2 + (0-(-1))^2 = 2; mean=1."""
    logits = torch.tensor([[0.0, 9.0], [0.0, 9.0]])
    action_idx = torch.tensor([0, 0])
    returns = torch.tensor([1.0, -1.0])
    loss = dmc_mse_loss(logits, action_idx, returns)
    assert loss.item() == pytest.approx(1.0, abs=1e-6)


def test_dmc_mse_ignores_non_selected_logits():
    """Changing non-selected logits must NOT change loss."""
    logits_a = torch.tensor([[0.5, 0.0, 100.0]])
    logits_b = torch.tensor([[0.5, 99.0, -100.0]])
    action_idx = torch.tensor([0])
    returns = torch.tensor([1.0])
    la = dmc_mse_loss(logits_a, action_idx, returns)
    lb = dmc_mse_loss(logits_b, action_idx, returns)
    assert la.item() == pytest.approx(lb.item(), abs=1e-6)


def test_dmc_mse_gradient_flows_to_selected_logit_only():
    """Backward should set grad on logit[a] and 0 on others."""
    logits = torch.tensor([[0.0, 0.0, 0.0]], requires_grad=True)
    action_idx = torch.tensor([1])
    returns = torch.tensor([1.0])
    loss = dmc_mse_loss(logits, action_idx, returns)
    loss.backward()
    g = logits.grad.squeeze(0)
    assert g[0].item() == pytest.approx(0.0, abs=1e-6)
    assert g[2].item() == pytest.approx(0.0, abs=1e-6)
    assert g[1].item() != pytest.approx(0.0, abs=1e-3)


def test_dmc_mse_raises_on_logits_wrong_dim():
    """logits must be (B, N_act); 1D / 3D must raise."""
    bad = torch.tensor([1.0, 0.0])
    with pytest.raises(ValueError, match='logits must be'):
        dmc_mse_loss(bad, torch.tensor([0]), torch.tensor([1.0]))
    bad3 = torch.zeros(1, 1, 1)
    with pytest.raises(ValueError, match='logits must be'):
        dmc_mse_loss(bad3, torch.tensor([0]), torch.tensor([1.0]))


def test_dmc_mse_raises_on_action_idx_wrong_dim():
    logits = torch.zeros(2, 3)
    with pytest.raises(ValueError, match='action_idx must be'):
        dmc_mse_loss(logits, torch.zeros(2, 1, dtype=torch.long), torch.zeros(2))


def test_dmc_mse_raises_on_returns_wrong_dim():
    logits = torch.zeros(2, 3)
    with pytest.raises(ValueError, match='returns must be'):
        dmc_mse_loss(logits, torch.tensor([0, 0]), torch.zeros(2, 1))
