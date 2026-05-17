"""Phase 2 path verification for T2.7 mv of pool_spec.py.

OpenSpec change ``az-paradigm-rewrite/`` T2.7: the ADR-0011 per-player
pool resolution helper (``resolve_pool_refs`` + ``make_pool_spec``) is
mv'd from ``training/paradigms/az/legacy/pool_spec.py`` to
``training/paradigms/az/pool_spec.py`` as part of Phase 2 consolidation.

Three checks:
  1. Static: ``resolve_pool_refs`` + ``make_pool_spec`` resolve from
     the adapter top-level (``training.paradigms.az.pool_spec``).
  2. AST: adapter ``collector.py`` and ``paradigm.py`` have ZERO
     ``training.paradigms.az.legacy.pool_spec`` imports (T2.11 verify
     scope: adapter has zero legacy.* imports for mv'd modules).
  3. Behavioral: ``resolve_pool_refs(scenario)`` returns the same
     per-player ref dict regardless of import path.
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib

import pytest


class TestNewPathResolves:
    """Check 1: public symbols importable from the adapter top-level."""

    def test_resolve_pool_refs_importable_from_adapter_toplevel(self):
        mod = importlib.import_module('training.paradigms.az.pool_spec')
        assert hasattr(mod, 'resolve_pool_refs'), 'resolve_pool_refs missing from new path'

    def test_make_pool_spec_importable_from_adapter_toplevel(self):
        mod = importlib.import_module('training.paradigms.az.pool_spec')
        assert hasattr(mod, 'make_pool_spec'), 'make_pool_spec missing from new path'

    def test_resolve_pool_refs_module_is_adapter(self):
        from training.paradigms.az.pool_spec import resolve_pool_refs

        assert resolve_pool_refs.__module__ == 'training.paradigms.az.pool_spec', (
            f'resolve_pool_refs.__module__ = {resolve_pool_refs.__module__!r}; '
            'expected adapter, not a legacy re-export.'
        )

    def test_resolve_pool_refs_defined_in_adapter_file(self):
        from training.paradigms.az.pool_spec import resolve_pool_refs

        src_file = inspect.getsourcefile(resolve_pool_refs)
        assert src_file is not None
        assert src_file.endswith('training/paradigms/az/pool_spec.py'), (
            f'resolve_pool_refs source = {src_file!r}; expected adapter path (not legacy/).'
        )


class TestLegacyPathGone:
    """The pre-mv legacy module file must be physically gone, not a shim."""

    def test_legacy_file_removed(self):
        repo_root = pathlib.Path(__file__).resolve().parents[2]
        legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'pool_spec.py'
        assert not legacy_path.exists(), (
            f'legacy pool_spec.py still present at {legacy_path} — mv incomplete or shim left behind'
        )

    def test_legacy_import_fails(self):
        with pytest.raises(ImportError):
            importlib.import_module('training.paradigms.az.legacy.pool_spec')


class TestAdapterImportTopology:
    """Check 2: adapter source AST has ZERO ``legacy.pool_spec`` imports
    (T2.11 verify scope)."""

    def _assert_no_legacy_pool_spec_import(self, module_name: str):
        mod = importlib.import_module(module_name)
        adapter_path = pathlib.Path(mod.__file__)
        tree = ast.parse(adapter_path.read_text())
        offending = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                if (node.module or '') == 'training.paradigms.az.legacy.pool_spec':
                    offending.append(f'from {node.module} import ...')
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'training.paradigms.az.legacy.pool_spec':
                        offending.append(f'import {alias.name}')
        assert not offending, (
            f'Adapter {module_name} must have zero legacy.pool_spec imports (T2.11). Found: {offending}'
        )

    def test_collector_has_no_legacy_pool_spec_import(self):
        self._assert_no_legacy_pool_spec_import('training.paradigms.az.collector')

    def test_paradigm_has_no_legacy_pool_spec_import(self):
        self._assert_no_legacy_pool_spec_import('training.paradigms.az.paradigm')


class TestBehavioral:
    """Check 3: resolve_pool_refs works end-to-end on a tiny fixture."""

    def test_resolve_pool_refs_returns_per_player_list(self):
        """Smoke: build a real ScenarioCfg, resolve pool refs, expect a
        dict keyed by player id (0/1) with non-empty list values.

        Mirrors the fixture pattern in test_az_async_collector.py: a
        2-pool (v_legacy + test_basic) scenario using 赤蝶."""
        from training.core.config.base import ScenarioCfg
        from training.paradigms.az.pool_spec import resolve_pool_refs

        scen = ScenarioCfg(team_0=['赤蝶'], team_1=['赤蝶'], pool=['v_legacy', 'test_basic'])
        out = resolve_pool_refs(scen)
        assert isinstance(out, dict)
        assert set(out.keys()) == {0, 1}, f'expected player ids {{0,1}}, got {set(out.keys())}'
        for p, refs in out.items():
            assert isinstance(refs, list), f'player {p} refs not a list: {type(refs).__name__}'
            assert len(refs) > 0, f'player {p} got empty refs — deck likely failed to populate'
            assert all(isinstance(r, int) for r in refs), f'player {p} contains non-int refs'
