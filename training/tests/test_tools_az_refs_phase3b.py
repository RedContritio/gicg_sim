"""Import-topology guard for tools/{debug,probe,profile} AZ refs (Phase 3b).

After the Phase 3b batch update (OpenSpec change ``az-paradigm-rewrite/``
T3b), active diag/probe/profile tools MUST import all AZ symbols from
the adapter top-level (``training.paradigms.az.*``); none may carry
``training.paradigms.az.legacy.*`` import paths.

Coverage:
    * AST scan — verify zero ``training.paradigms.az.legacy`` imports in
      the in-scope files (allows the historical "legacy" string token to
      remain in error messages / docstrings).
    * Import smoke — each module imports without ImportError, exercising
      the new adapter paths through Python's real loader.

The covered tools are diag-only (not production blocking) but break loudly
if their imports rot, so this guard runs in Phase 1 gate alongside the
adapter unit tests.

IR cutover (2026-05-19) deleted ``diag_hook_path`` + ``probe_numeric_sensitivity``
+ ``probe_numeric_sensitivity_core`` — they probed the obsolete (hook_types,
hook_values) token-pair schema, replaced by IR ops in the static obs.
"""

from __future__ import annotations

import ast
import importlib
import pathlib

import pytest

TOOLS = (
    'tools.debug.diag_champion_strength',
    'tools.debug.diag_is_mcts_baseline',
    'tools.debug.diag_is_mcts_with_rollout',
    'tools.debug.diag_net_plus_mcts',
    'tools.profile.profile_parallel',
    'tools.profile.profile_smoke',
)


def _module_path(repo_root: pathlib.Path, dotted: str) -> pathlib.Path:
    return repo_root.joinpath(*dotted.split('.')).with_suffix('.py')


def _legacy_import_names(tree: ast.AST) -> list[str]:
    """Return any ``training.paradigms.az.legacy*`` module names referenced
    by ``import`` / ``from ... import`` statements in the AST.

    String literals containing the word "legacy" (error messages /
    docstrings) are deliberately ignored — this guard targets imports
    only.
    """
    needle = 'training.paradigms.az.legacy'
    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.startswith(needle):
                    offenders.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if mod.startswith(needle):
                offenders.append(mod)
    return offenders


@pytest.mark.parametrize('dotted', TOOLS)
def test_tool_has_zero_legacy_imports(dotted: str) -> None:
    """AST scan: each in-scope tool has zero ``legacy.*`` imports."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    path = _module_path(repo_root, dotted)
    assert path.is_file(), f'expected tool source file at {path}'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    offenders = _legacy_import_names(tree)
    assert not offenders, f'{dotted} still imports legacy paths: {offenders} — should use adapter top-level'


@pytest.mark.parametrize('dotted', TOOLS)
def test_tool_module_imports_clean(dotted: str) -> None:
    """Import smoke: each tool loads without ImportError under the new paths."""
    mod = importlib.import_module(dotted)
    assert mod.__name__ == dotted
