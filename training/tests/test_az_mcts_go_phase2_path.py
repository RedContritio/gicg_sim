"""Phase 2 path verification for T2.10 mv of mcts_go + mcts_go_bindings.

OpenSpec change `az-paradigm-rewrite/` T2.10: the Go ctypes binding
(libgicg.{dylib,dll,so} loader for IS-MCTS) is mv'd from
``training/paradigms/az/legacy/{mcts_go,mcts_go_bindings}.py`` to
``training/paradigms/az/{mcts_go,mcts_go_bindings}.py`` as part of
Phase 2 consolidation.

This test pins:
  - the new adapter top-level path resolves
  - the old legacy path is gone (ImportError)
  - ctypes binding still loads libgicg (smoke)
  - public symbols are intact
"""

from __future__ import annotations

import importlib

import pytest


class TestNewPathResolves:
    def test_import_mcts_go_at_adapter_top_level(self):
        mod = importlib.import_module('training.paradigms.az.mcts_go')
        assert hasattr(mod, 'mcts_search_go'), 'mcts_search_go missing from new path'

    def test_import_mcts_go_bindings_at_adapter_top_level(self):
        mod = importlib.import_module('training.paradigms.az.mcts_go_bindings')
        assert hasattr(mod, 'ensure_lib'), 'ensure_lib missing from new path'
        assert hasattr(mod, 'make_eval_callbacks'), 'make_eval_callbacks missing from new path'
        assert hasattr(mod, 'SendCallbackType'), 'SendCallbackType missing from new path'
        assert hasattr(mod, 'RecvCallbackType'), 'RecvCallbackType missing from new path'


class TestLegacyPathGone:
    def test_legacy_mcts_go_import_fails(self):
        with pytest.raises(ImportError):
            importlib.import_module('training.paradigms.az.legacy.mcts_go')

    def test_legacy_mcts_go_bindings_import_fails(self):
        with pytest.raises(ImportError):
            importlib.import_module('training.paradigms.az.legacy.mcts_go_bindings')


class TestCtypesBindingLoads:
    def test_ensure_lib_loads_libgicg(self):
        """Smoke: ctypes CDLL load + MCTSSearch symbol bind succeeds.

        Confirms libgicg lookup path is unaffected by the mv — _find_lib()
        is anchored to ``gicg_env/engine.py`` location, not the caller's
        file, so the relative path computation is invariant under mv."""
        from training.paradigms.az.mcts_go_bindings import ensure_lib

        lib = ensure_lib()
        assert lib is not None
        assert hasattr(lib, 'MCTSSearch')
        # Bound argtypes should be a 9-tuple per ensure_lib body.
        assert len(lib.MCTSSearch.argtypes) == 9

    def test_ensure_lib_is_idempotent(self):
        """Second call returns the cached _lib singleton."""
        from training.paradigms.az.mcts_go_bindings import ensure_lib

        lib1 = ensure_lib()
        lib2 = ensure_lib()
        assert lib1 is lib2, 'ensure_lib must cache the CDLL singleton'
