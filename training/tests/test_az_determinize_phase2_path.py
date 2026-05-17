"""Import-topology guard for the AZ Phase 2 mv of ``determinize.py``.

After the Phase 2 β2 mv (OpenSpec change ``az-paradigm-rewrite/`` T2.2),
the Bayesian-Dirichlet determinization sampler MUST be importable from
the adapter top-level (``training.paradigms.az.determinize``), and the
legacy path (``training.paradigms.az.legacy.determinize``) MUST no
longer be importable by any active code path.

Covered: static import resolution + adapter file AST cleanliness +
negative (legacy path raises ImportError) + behavioral smoke for
``sample_opponent_dice``.
"""

from __future__ import annotations

import ast
import importlib
import pathlib
import random

import numpy as np
import pytest


ADAPTER_PUBLIC_NAMES = (
    'PublicObservation',
    'HiddenState',
    'CardPoolSpec',
    'SharedFixedPool',
    'PerOpponentPool',
    'sample_opponent_dice',
    'sample_hidden_state',
    'apply_determinization',
)


def test_determinize_importable_from_adapter_toplevel():
    """``training.paradigms.az.determinize`` exposes the full public surface."""
    mod = importlib.import_module('training.paradigms.az.determinize')
    for name in ADAPTER_PUBLIC_NAMES:
        assert hasattr(mod, name), f'{name} missing from new adapter-level path'


def test_legacy_determinize_path_gone():
    """The pre-mv legacy module file must be physically gone, not a shim."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'determinize.py'
    assert not legacy_path.exists(), (
        f'legacy determinize.py still present at {legacy_path} — mv incomplete or shim left behind'
    )


def test_legacy_determinize_import_fails():
    """No code path may import the legacy module path."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('training.paradigms.az.legacy.determinize')


def test_no_active_legacy_determinize_imports_in_tree():
    """grep-style guard: no .py file imports ``legacy.determinize`` after the mv.

    This test file itself contains the needle strings (as test data),
    so the self-path is excluded.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    self_path = pathlib.Path(__file__).resolve()
    needles = (
        'from training.paradigms.az.legacy.determinize',
        'import training.paradigms.az.legacy.determinize',
    )
    offenders: list[str] = []
    for py in repo_root.rglob('*.py'):
        if py.resolve() == self_path:
            continue
        parts = set(py.parts)
        if {'.venv', 'venv', 'build', 'dist', '.git', '.claude'} & parts:
            continue
        try:
            text = py.read_text(encoding='utf-8')
        except (UnicodeDecodeError, OSError):
            continue
        if any(n in text for n in needles):
            offenders.append(str(py.relative_to(repo_root)))
    assert not offenders, f'legacy.determinize imports still present in: {offenders}'


def _adapter_modules_ast() -> list[tuple[str, ast.Module]]:
    """Return (path, parsed AST) for the AZ adapter top-level modules per design.

    Excludes ``mcts_go.py`` (was moved in T2.10; legitimately re-exports a
    determinize dependency through the adapter surface) — wait, no: per
    design "all imports under adapter must point to new top-level path";
    mcts_go.py IS part of the adapter, so we DO include it.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    adapter_dir = repo_root / 'training' / 'paradigms' / 'az'
    out: list[tuple[str, ast.Module]] = []
    for py in sorted(adapter_dir.glob('*.py')):
        if py.name == '__init__.py':
            continue
        out.append((str(py.relative_to(repo_root)), ast.parse(py.read_text(encoding='utf-8'))))
    return out


def test_adapter_modules_dont_import_legacy_determinize():
    """AST guard: no adapter top-level .py imports legacy.determinize."""
    forbidden_prefix = 'training.paradigms.az.legacy.determinize'
    offenders: list[str] = []
    for rel_path, mod in _adapter_modules_ast():
        for node in ast.walk(mod):
            if isinstance(node, ast.ImportFrom):
                if node.module and node.module.startswith(forbidden_prefix):
                    offenders.append(f'{rel_path}: from {node.module}')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith(forbidden_prefix):
                        offenders.append(f'{rel_path}: import {alias.name}')
    assert not offenders, f'adapter modules still import legacy.determinize: {offenders}'


def test_sample_opponent_dice_smoke_via_adapter_path():
    """Behavioral smoke: sample_opponent_dice returns correct shape + sums."""
    from training.paradigms.az.determinize import sample_opponent_dice
    from training.core.obs_constants import DICE_COLOR_COUNT

    rng = random.Random(0xDEADBEEF)
    draws = sample_opponent_dice(rng, total_count=8)
    assert isinstance(draws, np.ndarray)
    assert draws.shape == (DICE_COLOR_COUNT,)
    assert draws.dtype == np.int32
    assert int(draws.sum()) == 8

    # zero total ⇒ all zeros, no RNG draw
    empty = sample_opponent_dice(rng, total_count=0)
    assert empty.shape == (DICE_COLOR_COUNT,)
    assert int(empty.sum()) == 0

    # invalid evidence length triggers contract raise
    with pytest.raises(ValueError):
        sample_opponent_dice(rng, total_count=4, paid_counts=[1, 2])
