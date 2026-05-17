"""Import-topology guard for the AZ Phase 2 mv of ``train_az.py``.

After the Phase 2 ε2 mv (OpenSpec change ``az-paradigm-rewrite/`` T2.8),
``train_az`` and ``RunResult`` MUST be importable from the adapter
top-level (``training.paradigms.az.train_az``), and the legacy path
(``training.paradigms.az.legacy.train_az``) MUST no longer be importable
by any active code path.

Note: ``train_az.py`` still transitively imports
``training.paradigms.az.legacy.config`` and
``training.paradigms.az.legacy.train_loop.*``. These siblings are NOT in
T2.8 scope (they will be promoted in later sub-tasks) and are explicitly
excluded from the topology check.
"""

from __future__ import annotations

import importlib
import inspect
import pathlib

import pytest


def test_train_az_importable_from_adapter_toplevel():
    """``training.paradigms.az.train_az`` exposes the public surface."""
    mod = importlib.import_module('training.paradigms.az.train_az')
    assert hasattr(mod, 'train_az'), 'train_az missing from new path'
    # RunResult is re-exported via the train_loop.run_result import chain.
    # train_az.py imports it for its function signature, so it's
    # available at module attribute level.
    assert hasattr(mod, 'RunResult'), 'RunResult missing from new path'


def test_train_az_module_is_adapter():
    """``train_az`` function's __module__ must point at the adapter."""
    from training.paradigms.az.train_az import train_az

    assert train_az.__module__ == 'training.paradigms.az.train_az', (
        f'train_az.__module__ = {train_az.__module__!r}; expected adapter, not a legacy re-export.'
    )


def test_train_az_defined_in_adapter_file():
    """The function source file must be the adapter, not legacy/train_az.py."""
    from training.paradigms.az.train_az import train_az

    src_file = inspect.getsourcefile(train_az)
    assert src_file is not None
    assert src_file.endswith('training/paradigms/az/train_az.py'), (
        f'train_az source = {src_file!r}; expected adapter path.'
    )
    assert 'legacy/train_az.py' not in src_file, (
        f'train_az source = {src_file!r}; legacy/train_az.py should be gone after T2.8.'
    )


def test_legacy_train_az_path_gone():
    """The pre-mv legacy module file must be physically gone, not a shim."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'train_az.py'
    assert not legacy_path.exists(), (
        f'legacy train_az.py still present at {legacy_path} — mv incomplete or shim left behind'
    )


def test_legacy_train_az_import_fails():
    """No code path may import the legacy module path."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('training.paradigms.az.legacy.train_az')


def test_no_active_legacy_train_az_imports_in_tree():
    """grep-style guard: no .py file imports ``legacy.train_az`` after the mv.

    This test file itself contains the needle strings (as test data),
    so the self-path is excluded.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    self_path = pathlib.Path(__file__).resolve()
    needles = (
        'from training.paradigms.az.legacy.train_az',
        'import training.paradigms.az.legacy.train_az',
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
    assert not offenders, f'legacy.train_az imports still present in: {offenders}'
