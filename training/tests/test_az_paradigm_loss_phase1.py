"""Phase 1 T1.2 — loss adapter import topology + numeric smoke.

Verifies:
1. ``training.paradigms.az.loss`` does NOT import anything from
   ``training.paradigms.az.legacy`` (any submodule). Adapter must reach
   into ``training.paradigms.az._az_losses`` for ``az_losses`` directly
   (post Phase 2F move from legacy/loss.py).
2. ``AZLoss.compute`` still produces a finite scalar loss + breakdown
   dict with the expected key set on a tiny dummy batch (numeric
   smoke — guards against accidental signature breakage when the
   import path changes).
"""

from __future__ import annotations

import ast
import pathlib

import pytest
import torch

import training.paradigms.az.loss as loss_mod
from training.core.protocols import Batch, LossResult
from training.paradigms.az.loss import AZLoss


def _collect_import_modules(py_path: pathlib.Path) -> set[str]:
    src = py_path.read_text()
    tree = ast.parse(src)
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
    return modules


# ---------- import topology ---------- #


def test_az_loss_no_legacy_az_imports():
    """Adapter loss MUST NOT import from training.paradigms.az.legacy.X."""
    py_path = pathlib.Path(loss_mod.__file__)
    modules = _collect_import_modules(py_path)
    bad = {m for m in modules if m.startswith('training.paradigms.az.legacy')}
    assert not bad, f'loss.py imports legacy.az modules: {sorted(bad)}'


def test_az_loss_imports_paradigm_az_losses():
    """Adapter loss must reach az_losses via the paradigm-local module
    (post core-network-generic-promotion Phase 2F: az_losses moved from
    legacy/loss.py to paradigms/az/_az_losses.py per spec delta R2)."""
    py_path = pathlib.Path(loss_mod.__file__)
    modules = _collect_import_modules(py_path)
    assert 'training.paradigms.az._az_losses' in modules, (
        f'loss.py must import az_losses from training.paradigms.az._az_losses; current imports: {sorted(modules)}'
    )


# ---------- numeric smoke ---------- #


class _StubAZNetwork:
    """Minimal forward_batch stub returning fixed logits/value/delta."""

    def __init__(self, logits, value):
        self._logits = logits
        self._value = value
        self.net = torch.nn.Linear(1, 1)

    def forward_batch(self, batch_dict):
        return self._logits, self._value, torch.zeros(1)


class _StubTrainCfg:
    l2_coef = 0.0
    entropy_coef = 0.0
    delta_aux_coef = 0.0


class _StubParadigmCfg:
    train = _StubTrainCfg()


def _make_batch():
    return Batch(
        data={
            'pi_target': torch.tensor([[1.0, 0.0]], dtype=torch.float32),
            'z_target': torch.tensor([0.5], dtype=torch.float32),
            'legal_mask': torch.tensor([[True, True]], dtype=torch.bool),
        },
        size=1,
    )


def test_az_loss_compute_returns_loss_result():
    """Smoke: AZLoss.compute returns LossResult with finite loss + dict."""
    loss_fn = AZLoss(_StubParadigmCfg())
    logits = torch.tensor([[5.0, 0.0]], dtype=torch.float32)
    value = torch.tensor([0.3], dtype=torch.float32)
    res = loss_fn.compute(_StubAZNetwork(logits, value), _make_batch())
    assert isinstance(res, LossResult)
    assert torch.is_tensor(res.loss)
    assert torch.isfinite(res.loss).item()
    assert res.loss.ndim == 0  # scalar


def test_az_loss_breakdown_has_canonical_keys():
    """Breakdown dict carries the canonical 5 keys for metrics ingest."""
    loss_fn = AZLoss(_StubParadigmCfg())
    logits = torch.tensor([[5.0, 0.0]], dtype=torch.float32)
    value = torch.tensor([0.3], dtype=torch.float32)
    res = loss_fn.compute(_StubAZNetwork(logits, value), _make_batch())
    for k in ('loss', 'policy_loss', 'value_loss', 'l2', 'entropy'):
        assert k in res.breakdown, f'breakdown missing {k}: got {sorted(res.breakdown.keys())}'
        assert isinstance(res.breakdown[k], float)


def test_az_loss_dtype_preserved_float32():
    """Loss output dtype must match input logits dtype (float32 default)."""
    loss_fn = AZLoss(_StubParadigmCfg())
    logits = torch.tensor([[5.0, 0.0]], dtype=torch.float32)
    value = torch.tensor([0.3], dtype=torch.float32)
    res = loss_fn.compute(_StubAZNetwork(logits, value), _make_batch())
    assert res.loss.dtype == torch.float32


def test_az_loss_missing_required_key_raises():
    """Contract: missing pi_target / z_target / legal_mask → ValueError."""
    loss_fn = AZLoss(_StubParadigmCfg())
    incomplete = Batch(data={'pi_target': torch.zeros(1, 2)}, size=1)
    logits = torch.tensor([[1.0, 0.0]])
    value = torch.tensor([0.0])
    with pytest.raises(ValueError, match='missing required keys'):
        loss_fn.compute(_StubAZNetwork(logits, value), incomplete)
