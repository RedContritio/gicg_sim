"""NaNGuard dump + raise behavior."""

from __future__ import annotations

from pathlib import Path

import pytest
import torch

from training.core.nan_guard import NaNGuard


def test_finite_no_op():
    guard = NaNGuard()
    loss = torch.tensor(1.5)
    grad_norm = torch.tensor(0.3)
    guard.check(loss, grad_norm, train_step=10)  # no raise


def test_nan_loss_raises(tmp_path):
    guard = NaNGuard(artifacts_dir=tmp_path)
    loss = torch.tensor(float('nan'))
    grad_norm = torch.tensor(0.3)
    with pytest.raises(RuntimeError, match='non-finite loss'):
        guard.check(loss, grad_norm, train_step=5)
    # evidence dump
    dump = tmp_path / 'nan_dump_5'
    assert dump.exists()
    assert (dump / 'diag.json').exists()


def test_inf_grad_raises(tmp_path):
    guard = NaNGuard(artifacts_dir=tmp_path)
    loss = torch.tensor(1.0)
    grad_norm = torch.tensor(float('inf'))
    with pytest.raises(RuntimeError, match='non-finite'):
        guard.check(loss, grad_norm, train_step=7)


def test_scalar_finite_check(tmp_path):
    guard = NaNGuard(artifacts_dir=tmp_path)
    # Pure python float path
    guard.check(0.5, 0.3, train_step=1)
    with pytest.raises(RuntimeError):
        guard.check(float('nan'), 0.3, train_step=2)
