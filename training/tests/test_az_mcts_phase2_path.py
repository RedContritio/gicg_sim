"""Import-topology guard for the AZ Phase 2 mv of ``mcts/`` (T2.1).

After the Phase 2 γ mv (OpenSpec change ``az-paradigm-rewrite/`` T2.1),
the IS-MCTS Python implementation MUST be importable as a subpackage
from the adapter top-level (``training.paradigms.az.mcts``), and the
legacy subdir (``training.paradigms.az.legacy.mcts``) MUST no longer
be importable by any active code path.

Covered: static import resolution (package + each submodule) + adapter
file AST cleanliness + negative (legacy path raises ImportError) +
filesystem absence guard.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest


# Public surface kept stable through the mv — should resolve from the
# new adapter top-level path.
MCTS_PUBLIC_NAMES = (
    'ACTION_TUNE',
    'ActionId',
    'MCTSConfig',
    'MCTSNode',
    'MCTSProfile',
    'build_action_id',
    'compute_annealed_lambda',
    'legal_ids_from_env',
    'mcts_search',
    'mcts_search_parallel',
    'rng_dirichlet',
    '_apply_leaf_mixing',
    '_argmax_visits',
    '_commit_parallel_rollout',
    '_descend_with_vl',
    '_detect_discovery',
    '_eval_leaf',
    '_find_action_index',
    '_InFlightRollout',
    '_pick_action_from_visits',
    '_puct_select',
    '_random_rollout_value',
)

# Each submodule must be independently importable so cross-imports
# (relative or absolute) resolve under the new path.
MCTS_SUBMODULES = (
    'action_id',
    'config',
    'node',
    'parallel',
    'rollout',
    'run_rollout',
    'search',
    'search_parallel',
    'utils',
)


def test_mcts_package_importable_from_adapter_toplevel():
    """``training.paradigms.az.mcts`` exposes the full public surface."""
    mod = importlib.import_module('training.paradigms.az.mcts')
    for name in MCTS_PUBLIC_NAMES:
        assert hasattr(mod, name), f'{name} missing from new adapter-level path'


@pytest.mark.parametrize('submodule', MCTS_SUBMODULES)
def test_mcts_submodule_importable(submodule):
    """Each MCTS submodule is independently importable post-mv."""
    importlib.import_module(f'training.paradigms.az.mcts.{submodule}')


def test_legacy_mcts_dir_gone():
    """The pre-mv legacy subdir must be physically gone, not a shim."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    legacy_dir = repo_root / 'training' / 'paradigms' / 'az' / 'legacy' / 'mcts'
    assert not legacy_dir.exists(), f'legacy mcts/ still present at {legacy_dir} — mv incomplete or shim left behind'


def test_legacy_mcts_import_fails():
    """No code path may import the legacy package path."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module('training.paradigms.az.legacy.mcts')


def test_no_active_legacy_mcts_imports_in_tree():
    """grep-style guard: no .py file imports ``legacy.mcts`` after the mv.

    This test file itself contains the needle strings (as test data),
    so the self-path is excluded.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    self_path = pathlib.Path(__file__).resolve()
    needles = (
        'from training.paradigms.az.legacy.mcts',
        'import training.paradigms.az.legacy.mcts',
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
    assert not offenders, f'legacy.mcts imports still present in: {offenders}'


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


def test_adapter_modules_dont_import_legacy_mcts():
    """AST guard: no adapter top-level .py imports legacy.mcts."""
    forbidden_prefix = 'training.paradigms.az.legacy.mcts'
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
    assert not offenders, f'adapter modules still import legacy.mcts: {offenders}'


def test_mcts_config_smoke_via_adapter_path():
    """Behavioral smoke: MCTSConfig constructs with default args via new path."""
    from training.paradigms.az.mcts import MCTSConfig

    cfg = MCTSConfig(
        n_rollouts=1,
        max_rollout_depth=10,
        parallel_rollouts=1,
        dirichlet_eps=0.0,
        temperature_switch_step=0,
        value_mix_lambda=1.0,
        prior_mix_lambda=1.0,
        lambda_anneal_games=0,
        profile=False,
        discovery_checkpoints=(),
    )
    assert cfg.n_rollouts == 1
    assert cfg.max_rollout_depth == 10
