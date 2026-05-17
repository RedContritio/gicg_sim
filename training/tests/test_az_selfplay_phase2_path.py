"""Import-topology guard for the AZ Phase 2 mv of ``selfplay.py``.

After the Phase 2 ε1 mv (OpenSpec change ``az-paradigm-rewrite/`` T2.3),
the canonical ``play_self_game`` implementation MUST be importable from
the adapter top-level (``training.paradigms.az.selfplay``), and the
legacy path (``training.paradigms.az.legacy.selfplay``) MUST no longer
be importable by any active code path.

Covered: static import resolution + adapter file AST cleanliness +
negative (legacy path raises ImportError) + tree-wide grep guard.

Behavioral coverage stays in ``test_selfplay.py`` (full play_self_game
integration) — duplicating it here would re-spin a real game (slow) for
no marginal signal.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest


ADAPTER_PUBLIC_NAMES = (
    'SelfPlayResult',
    'play_self_game',
)


def test_selfplay_importable_from_adapter_toplevel():
    """``training.paradigms.az.selfplay`` exposes the canonical public surface."""
    mod = importlib.import_module('training.paradigms.az.selfplay')
    for name in ADAPTER_PUBLIC_NAMES:
        assert hasattr(mod, name), f'{name} missing from new adapter-level path'


def test_legacy_selfplay_path_gone():
    """The pre-mv legacy module file must be physically gone, not a shim."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'selfplay.py'
    assert not legacy_path.exists(), (
        f'legacy selfplay.py still present at {legacy_path} — mv incomplete or shim left behind'
    )


def test_legacy_selfplay_import_fails():
    """No code path may import the legacy module path."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('training.paradigms.az.legacy.selfplay')


def test_no_active_legacy_selfplay_imports_in_tree():
    """grep-style guard: no .py file imports ``legacy.selfplay`` after the mv.

    This test file itself contains the needle strings (as test data),
    so the self-path is excluded.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    self_path = pathlib.Path(__file__).resolve()
    needles = (
        'from training.paradigms.az.legacy.selfplay',
        'import training.paradigms.az.legacy.selfplay',
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
    assert not offenders, f'legacy.selfplay imports still present in: {offenders}'


def _adapter_modules_ast() -> list[tuple[str, ast.Module]]:
    """Return (path, parsed AST) for the AZ adapter top-level modules."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    adapter_dir = repo_root / 'training' / 'paradigms' / 'az'
    out: list[tuple[str, ast.Module]] = []
    for py in sorted(adapter_dir.glob('*.py')):
        if py.name == '__init__.py':
            continue
        out.append((str(py.relative_to(repo_root)), ast.parse(py.read_text(encoding='utf-8'))))
    return out


def test_adapter_modules_dont_import_legacy_selfplay():
    """AST guard: no adapter top-level .py imports legacy.selfplay."""
    forbidden_prefix = 'training.paradigms.az.legacy.selfplay'
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
    assert not offenders, f'adapter modules still import legacy.selfplay: {offenders}'
