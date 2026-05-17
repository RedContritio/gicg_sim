"""Import-topology guard for the AZ Phase 2 mv of ``arena.py``.

After the Phase 2 α1 mv (OpenSpec change ``az-paradigm-rewrite/`` T2.4),
``arena_match`` and ``ArenaResult`` MUST be importable from the adapter
top-level (``training.paradigms.az.arena``), and the legacy path
(``training.paradigms.az.legacy.arena``) MUST no longer be importable
by any active code path.
"""

from __future__ import annotations

import importlib
import pathlib

import pytest


def test_arena_importable_from_adapter_toplevel():
    """``training.paradigms.az.arena`` exposes the public surface."""
    mod = importlib.import_module('training.paradigms.az.arena')
    assert hasattr(mod, 'arena_match'), 'arena_match missing from new path'
    assert hasattr(mod, 'ArenaResult'), 'ArenaResult missing from new path'


def test_legacy_arena_path_gone():
    """The pre-mv legacy module file must be physically gone, not a shim."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'arena.py'
    assert not legacy_path.exists(), (
        f'legacy arena.py still present at {legacy_path} — mv incomplete or shim left behind'
    )


def test_legacy_arena_import_fails():
    """No code path may import the legacy module path."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('training.paradigms.az.legacy.arena')


def test_no_active_legacy_arena_imports_in_tree():
    """grep-style guard: no .py file imports ``legacy.arena`` after the mv.

    This test file itself contains the needle strings (as test data),
    so the self-path is excluded.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    self_path = pathlib.Path(__file__).resolve()
    needles = (
        'from training.paradigms.az.legacy.arena',
        'import training.paradigms.az.legacy.arena',
    )
    offenders: list[str] = []
    for py in repo_root.rglob('*.py'):
        # skip vendored / venv / build artifacts + this test (which references the needle as data)
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
    assert not offenders, f'legacy.arena imports still present in: {offenders}'
