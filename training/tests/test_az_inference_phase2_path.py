"""Import-topology guard for the AZ Phase 2 mv of ``inference_pool`` + ``inference_worker``.

After the Phase 2 ε3 mv (OpenSpec change ``az-paradigm-rewrite/`` T2.9),
``ParallelInferencePool`` / ``PoolDeadlock`` / ``WorkerError`` MUST be
importable from the adapter top-level (``training.paradigms.az.inference_pool``)
and ``worker_loop`` from ``training.paradigms.az.inference_worker``.
The legacy paths MUST no longer be importable by any active code path.

Covered: static import resolution + adapter file AST cleanliness +
negative (legacy paths raise ImportError) + cross-import is intra-adapter
(pool → worker is the new top-level path, not legacy).
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest


ADAPTER_POOL_NAMES = ('ParallelInferencePool', 'PoolDeadlock', 'WorkerError')
ADAPTER_WORKER_NAMES = ('worker_loop',)


class TestNewPathImports:
    """Check 1: the adapter top-level path resolves and exposes the public surface."""

    def test_inference_pool_importable_from_adapter_toplevel(self):
        mod = importlib.import_module('training.paradigms.az.inference_pool')
        for name in ADAPTER_POOL_NAMES:
            assert hasattr(mod, name), f'{name} missing from new adapter-level inference_pool path'

    def test_inference_worker_importable_from_adapter_toplevel(self):
        mod = importlib.import_module('training.paradigms.az.inference_worker')
        for name in ADAPTER_WORKER_NAMES:
            assert hasattr(mod, name), f'{name} missing from new adapter-level inference_worker path'


class TestLegacyPathGone:
    """Check 2: the pre-mv legacy module files must be physically gone and unimportable."""

    def test_legacy_inference_pool_file_removed(self):
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'inference_pool.py'
        assert not legacy_path.exists(), (
            f'legacy inference_pool.py still present at {legacy_path} — mv incomplete or shim left behind'
        )

    def test_legacy_inference_worker_file_removed(self):
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'inference_worker.py'
        assert not legacy_path.exists(), (
            f'legacy inference_worker.py still present at {legacy_path} — mv incomplete or shim left behind'
        )

    def test_legacy_inference_pool_import_fails(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module('training.paradigms.az.legacy.inference_pool')

    def test_legacy_inference_worker_import_fails(self):
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module('training.paradigms.az.legacy.inference_worker')


class TestNoActiveLegacyReferences:
    """Check 3: grep-style guard — no .py file imports legacy.inference_pool or legacy.inference_worker.

    This test file itself contains the needle strings (as test data), so the self-path is excluded.
    """

    def _scan(self, needles: tuple[str, ...]) -> list[str]:
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        self_path = pathlib.Path(__file__).resolve()
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
        return offenders

    def test_no_active_legacy_inference_pool_imports(self):
        offenders = self._scan(
            (
                'from training.paradigms.az.legacy.inference_pool',
                'import training.paradigms.az.legacy.inference_pool',
            )
        )
        assert not offenders, f'legacy.inference_pool imports still present in: {offenders}'

    def test_no_active_legacy_inference_worker_imports(self):
        offenders = self._scan(
            (
                'from training.paradigms.az.legacy.inference_worker',
                'import training.paradigms.az.legacy.inference_worker',
            )
        )
        assert not offenders, f'legacy.inference_worker imports still present in: {offenders}'


class TestAdapterImportTopology:
    """Check 4: adapter source AST has ZERO ``legacy.inference_pool`` / ``legacy.inference_worker`` imports
    (T2.11 verify scope). The pool ⟷ worker cross-import MUST use the new top-level path."""

    FORBIDDEN_PREFIXES = (
        'training.paradigms.az.legacy.inference_pool',
        'training.paradigms.az.legacy.inference_worker',
    )

    def _assert_no_forbidden_import(self, module_name: str) -> None:
        mod = importlib.import_module(module_name)
        adapter_path = pathlib.Path(mod.__file__)
        tree = ast.parse(adapter_path.read_text(encoding='utf-8'))
        offending: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = node.module or ''
                if any(module.startswith(p) for p in self.FORBIDDEN_PREFIXES):
                    offending.append(f'from {module} import ...')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if any(alias.name.startswith(p) for p in self.FORBIDDEN_PREFIXES):
                        offending.append(f'import {alias.name}')
        assert not offending, (
            f'Adapter {module_name} must have zero legacy.inference_* imports (T2.11). Found: {offending}'
        )

    def test_inference_pool_has_no_legacy_inference_import(self):
        """The cross-import (pool → worker) must use the new top-level path."""
        self._assert_no_forbidden_import('training.paradigms.az.inference_pool')

    def test_inference_worker_has_no_legacy_inference_import(self):
        self._assert_no_forbidden_import('training.paradigms.az.inference_worker')

    def test_cross_import_resolves_to_new_top_level(self):
        """Behavioral verification: importing inference_pool must load the worker
        from the adapter top-level path (not the legacy path).

        Spec: ``from training.paradigms.az.inference_worker import worker_loop``
        is the line inside inference_pool.py — any other binding indicates the mv
        wasn't applied cleanly."""
        import training.paradigms.az.inference_pool as pool_mod
        import training.paradigms.az.inference_worker as worker_mod

        # the private alias bound at module top
        assert hasattr(pool_mod, '_worker_loop'), 'inference_pool must alias the worker entry'
        assert pool_mod._worker_loop is worker_mod.worker_loop, (
            'inference_pool._worker_loop must point at the new top-level worker_loop, not a stale legacy binding'
        )
