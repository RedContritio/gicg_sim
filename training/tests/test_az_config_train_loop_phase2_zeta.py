"""Phase 2-ζ guard: AZ adapter must achieve STRICT T2.11 zero-legacy.

OpenSpec change ``az-paradigm-rewrite/`` Phase 2 T2.1-T2.10 moved/inlined
arena, buffer, mcts_go, pool_spec, determinize, mcts, network, selfplay,
train_az, inference_pool, inference_worker into the adapter top-level.
However, three adapter files (``train_az.py``, ``inference_pool.py``,
``inference_worker.py``) still imported ``legacy.config.AZConfig`` (+
``fixed_1v1_config``) and ``legacy.train_loop.{async_loop, run_result}``.

T2.ζ inlines AZConfig + preset builders into ``adapter/config.py``
(alongside the Phase 1 AZParadigmConfig) and the 4 train_loop modules
into a new ``adapter/train_loop/`` subdir, then switches all 6 adapter
imports off ``legacy.*``. After T2.ζ, ``training/paradigms/az/`` top-level
.py files (excluding the transitional ``legacy/`` subdir) must contain
ZERO ``legacy.*`` imports — which is the STRICT form of the T2.11 verify.

``legacy/{config.py, train_loop/}`` themselves stay alive in this phase
because tests + tools still reference ``legacy.config`` directly; those
will be promoted in Phase 5 (full ``git rm legacy/``).
"""

from __future__ import annotations

import ast
import importlib
import inspect
import pathlib

import pytest


ADAPTER_TOPLEVEL_FILES = (
    'training.paradigms.az.config',
    'training.paradigms.az.train_az',
    'training.paradigms.az.inference_pool',
    'training.paradigms.az.inference_worker',
    'training.paradigms.az.arena',
    'training.paradigms.az.buffer',
    'training.paradigms.az.collector',
    'training.paradigms.az.determinize',
    'training.paradigms.az.loss',
    'training.paradigms.az.mcts_go',
    'training.paradigms.az.mcts_go_bindings',
    'training.paradigms.az.network',
    'training.paradigms.az.paradigm',
    'training.paradigms.az.policy',
    'training.paradigms.az.pool_spec',
    'training.paradigms.az.selfplay',
    'training.paradigms.az.train_az',
)


# ---------------------------------------------------------------------------
# Module-import smoke (new paths must resolve)
# ---------------------------------------------------------------------------


def test_adapter_config_exposes_AZConfig():
    """``training.paradigms.az.config`` re-exports AZConfig + preset builders inline."""
    mod = importlib.import_module('training.paradigms.az.config')
    assert hasattr(mod, 'AZConfig'), 'AZConfig missing from adapter/config.py'
    assert hasattr(mod, 'fixed_1v1_config'), 'fixed_1v1_config missing from adapter/config.py'
    assert hasattr(mod, 'smoke_config'), 'smoke_config missing from adapter/config.py'
    assert hasattr(mod, 'random_1v1_config'), 'random_1v1_config missing from adapter/config.py'
    # AZParadigmConfig (Phase 1) must still be present alongside the inline copy.
    assert hasattr(mod, 'AZParadigmConfig'), 'AZParadigmConfig missing from adapter/config.py'


def test_adapter_train_loop_subpackage_resolves():
    """``training.paradigms.az.train_loop`` subdir + 4 modules all import-clean."""
    for sub in ('async_loop', 'helpers', 'run_result', 'stats_ingest'):
        full = f'training.paradigms.az.train_loop.{sub}'
        mod = importlib.import_module(full)
        assert mod is not None, f'{full} failed to import'


def test_adapter_train_loop_exports():
    """``run_async``, ``RunResult``, ``stats_ingest_loop``, and helpers
    are reachable at their new adapter paths."""
    from training.paradigms.az.train_loop.async_loop import run_async  # noqa: F401
    from training.paradigms.az.train_loop.helpers import (  # noqa: F401
        cpu_state_dict,
        ingest_trajectory,
        maybe_arena,
    )
    from training.paradigms.az.train_loop.run_result import RunResult  # noqa: F401
    from training.paradigms.az.train_loop.stats_ingest import stats_ingest_loop  # noqa: F401


# ---------------------------------------------------------------------------
# Module identity — functions must be defined in the adapter, not re-exported
# ---------------------------------------------------------------------------


def test_AZConfig_defined_in_adapter_config():
    """AZConfig's source file must be adapter/config.py, NOT legacy/config.py."""
    from training.paradigms.az.config import AZConfig

    src_file = inspect.getsourcefile(AZConfig)
    assert src_file is not None
    assert src_file.endswith('training/paradigms/az/config.py'), (
        f'AZConfig source = {src_file!r}; expected adapter/config.py.'
    )
    assert 'legacy/config.py' not in src_file, (
        f'AZConfig source = {src_file!r}; legacy/config.py should not be the canonical site after T2.ζ.'
    )


def test_run_async_defined_in_adapter_train_loop():
    """run_async's source file must be adapter/train_loop/async_loop.py."""
    from training.paradigms.az.train_loop.async_loop import run_async

    src_file = inspect.getsourcefile(run_async)
    assert src_file is not None
    assert src_file.endswith('training/paradigms/az/train_loop/async_loop.py'), (
        f'run_async source = {src_file!r}; expected adapter/train_loop/async_loop.py.'
    )
    assert 'legacy/train_loop' not in src_file, (
        f'run_async source = {src_file!r}; legacy/train_loop should not be the canonical site after T2.ζ.'
    )


def test_RunResult_defined_in_adapter_train_loop():
    """RunResult's source file must be adapter/train_loop/run_result.py."""
    from training.paradigms.az.train_loop.run_result import RunResult

    src_file = inspect.getsourcefile(RunResult)
    assert src_file is not None
    assert src_file.endswith('training/paradigms/az/train_loop/run_result.py'), (
        f'RunResult source = {src_file!r}; expected adapter/train_loop/run_result.py.'
    )


# ---------------------------------------------------------------------------
# AST grep — adapter top-level .py files import ZERO legacy.config/train_loop
# ---------------------------------------------------------------------------


def _file_imports_legacy_config_or_train_loop(path: pathlib.Path) -> list[str]:
    """Return list of legacy.config / legacy.train_loop imports found in
    ``path``. Empty list = clean."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, OSError, SyntaxError):
        return []
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if mod.startswith('training.paradigms.az.legacy.config') or mod.startswith(
                'training.paradigms.az.legacy.train_loop'
            ):
                hits.append(f'from {mod} import ...')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith('training.paradigms.az.legacy.config') or alias.name.startswith(
                    'training.paradigms.az.legacy.train_loop'
                ):
                    hits.append(f'import {alias.name}')
    return hits


def test_adapter_train_az_has_no_legacy_config_or_train_loop_import():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    path = repo_root / 'training' / 'paradigms' / 'az' / 'train_az.py'
    hits = _file_imports_legacy_config_or_train_loop(path)
    assert not hits, f'train_az.py still imports legacy.config / legacy.train_loop: {hits}'


def test_adapter_inference_pool_has_no_legacy_config_import():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    path = repo_root / 'training' / 'paradigms' / 'az' / 'inference_pool.py'
    hits = _file_imports_legacy_config_or_train_loop(path)
    assert not hits, f'inference_pool.py still imports legacy.config / legacy.train_loop: {hits}'


def test_adapter_inference_worker_has_no_legacy_config_import():
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    path = repo_root / 'training' / 'paradigms' / 'az' / 'inference_worker.py'
    hits = _file_imports_legacy_config_or_train_loop(path)
    assert not hits, f'inference_worker.py still imports legacy.config / legacy.train_loop: {hits}'


def test_strict_T2_11_no_legacy_import_in_adapter_toplevel():
    """STRICT T2.11 verify: no adapter top-level .py file may import
    ``training.paradigms.az.legacy.*`` at all.

    Scope = top-level *.py files immediately under ``paradigms/az/``,
    excluding the ``legacy/`` and ``mcts/`` subdir trees and excluding
    ``__init__.py`` (which only sets a package docstring).

    Note ``mcts/`` is an adapter subpackage (mv'd in T2.1) and must also
    stay clean.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    az_dir = repo_root / 'training' / 'paradigms' / 'az'
    offenders: dict[str, list[str]] = {}

    # Top-level adapter .py files
    for py in sorted(az_dir.glob('*.py')):
        if py.name == '__init__.py':
            continue
        hits = _scan_any_legacy_import(py)
        if hits:
            offenders[str(py.relative_to(repo_root))] = hits

    # Adapter subpackages (mcts/, train_loop/) — must also be clean.
    for sub in ('mcts', 'train_loop'):
        sub_dir = az_dir / sub
        if not sub_dir.is_dir():
            continue
        for py in sorted(sub_dir.rglob('*.py')):
            hits = _scan_any_legacy_import(py)
            if hits:
                offenders[str(py.relative_to(repo_root))] = hits

    assert not offenders, (
        'STRICT T2.11 violation — adapter top-level / sub-package files import legacy.*:\n'
        + '\n'.join(f'  {f}: {h}' for f, h in offenders.items())
    )


def _scan_any_legacy_import(path: pathlib.Path) -> list[str]:
    """Like ``_file_imports_legacy_config_or_train_loop`` but catches
    ANY ``training.paradigms.az.legacy.*`` import."""
    try:
        tree = ast.parse(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, OSError, SyntaxError):
        return []
    needle = 'training.paradigms.az.legacy'
    hits: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if mod.startswith(needle):
                hits.append(f'from {mod} import ...')
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(needle):
                    hits.append(f'import {alias.name}')
    return hits


# ---------------------------------------------------------------------------
# Behavioral smoke — AZConfig + fixed_1v1_config still build sensibly
# ---------------------------------------------------------------------------


def test_AZConfig_instantiates_via_smoke_config():
    """smoke_config() builds an AZConfig with non-default scenario/agent
    fields (those have no defaults — preset builders fill them)."""
    from training.paradigms.az.config import AZConfig, smoke_config

    cfg = smoke_config(data_dir=None)
    assert isinstance(cfg, AZConfig)
    assert cfg.scenario is not None, 'smoke_config did not fill .scenario'
    assert cfg.agent is not None, 'smoke_config did not fill .agent'
    assert cfg.n_games == 3
    assert cfg.write_artifacts is False


def test_fixed_1v1_config_returns_AZConfig():
    """fixed_1v1_config() builds a sensible AZConfig."""
    from training.paradigms.az.config import AZConfig, fixed_1v1_config

    cfg = fixed_1v1_config(data_dir=None)
    assert isinstance(cfg, AZConfig)
    assert cfg.n_games == 2000
    assert cfg.batch_size == 256
    assert cfg.agent.d_model == 128
    assert cfg.mcts.n_rollouts == 200
    assert cfg.run_label == 'fixed_1v1'
    assert cfg.write_artifacts is True
    # F1 ladder must be present (used by gauntlet — see fixed_1v1_config docstring)
    names = {b['name'] for b in cfg.gauntlet_greedy_baselines}
    assert names == {'F1-D1', 'F1-D2', 'F1-D3'}


def test_random_1v1_config_overrides_team_and_pool():
    """random_1v1_config builds on fixed_1v1_config + team/pool swap."""
    from training.paradigms.az.config import random_1v1_config

    cfg = random_1v1_config(data_dir=None)
    assert cfg.scenario.team_0 == ['赤蝶']
    assert cfg.scenario.team_1 == ['墨客']
    assert cfg.run_label == 'random_1v1'


def test_RunResult_dataclass_basic_shape():
    """RunResult dataclass instantiates with default lists."""
    from training.paradigms.az.train_loop.run_result import RunResult

    r = RunResult(n_games_played=0)
    assert r.n_games_played == 0
    assert r.training_stats == []
    assert r.selfplay_winners == []
    assert r.artifacts_dir is None


def test_helpers_have_expected_signatures():
    """ingest_trajectory + cpu_state_dict + maybe_arena are callables."""
    from training.paradigms.az.train_loop.helpers import (
        cpu_state_dict,
        ingest_trajectory,
        maybe_arena,
    )

    assert callable(ingest_trajectory)
    assert callable(cpu_state_dict)
    assert callable(maybe_arena)


# ---------------------------------------------------------------------------
# Legacy file gone — Phase 5 git rm executed (2026-05-16)
# ---------------------------------------------------------------------------


def test_legacy_config_file_gone():
    """legacy/config.py removed by Phase 5 (az-paradigm-rewrite, 2026-05-16)."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_path = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'config.py'
    assert not legacy_path.exists(), 'legacy/config.py still present — Phase 5 git rm incomplete'


def test_legacy_train_loop_dir_gone():
    """legacy/train_loop/ removed by Phase 5 (az-paradigm-rewrite, 2026-05-16)."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_dir = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'train_loop'
    assert not legacy_dir.exists(), 'legacy/train_loop/ still present — Phase 5 git rm incomplete'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
