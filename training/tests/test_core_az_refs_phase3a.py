"""Phase 3a AST guard — production core files must not import legacy.* AZ paths.

Background: Phase 2 (FU-W4-AZ-rewrite, T2.*) shipped adapter-top-level for
all AZ modules. T3a switches production core consumers
(``training/core/matchup/loaders.py`` + ``training/core/inference/server_loop/loop.py``)
from ``training.paradigms.az.legacy.*`` → ``training.paradigms.az.*``
adapter paths. This guard locks the switch so a future regression that
re-adds ``legacy.`` import fails fast in CI.

Scope is strictly the 2 core production files T3a owns. Other consumers
(tools/, other tests) are T3b/T3c scope.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TARGETS = (
    'training/core/matchup/loaders.py',
    'training/core/inference/server_loop/loop.py',
)
_FORBIDDEN_PREFIX = 'training.paradigms.az.legacy'


def _collect_imports(path: Path) -> list[str]:
    """Return every fully-qualified import target string in ``path``.

    Walks both ``Import`` and ``ImportFrom`` nodes; for ``from X import Y``
    only ``X`` is returned (we only care if the *source* module sits under
    the forbidden prefix, not what's pulled from it).
    """
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    out: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            out.append(node.module)
    return out


@pytest.mark.parametrize('rel_path', _TARGETS)
def test_no_legacy_az_import(rel_path: str) -> None:
    """Both T3a-owned core files must have zero ``legacy.*`` AZ imports."""
    path = _REPO_ROOT / rel_path
    assert path.exists(), f'T3a target missing: {path}'
    offenders = [mod for mod in _collect_imports(path) if mod.startswith(_FORBIDDEN_PREFIX)]
    assert not offenders, f'{rel_path} still imports forbidden legacy AZ modules: {offenders}'
