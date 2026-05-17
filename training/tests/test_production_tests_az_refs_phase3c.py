"""Import-topology guard for production tests AZ refs (Phase 3c).

After the Phase 3c batch update (OpenSpec change ``az-paradigm-rewrite/``
T3c), the 10 production test files MUST import all AZ symbols from the
adapter top-level (``training.paradigms.az.*``); none may carry
``training.paradigms.az.legacy.*`` import paths.

Phase 2 path tests (``test_az_*phase2*.py`` + ``test_az_*phase1*.py``)
intentionally KEEP ``training.paradigms.az.legacy`` import references —
they assert ``ImportError`` on the mv'd legacy modules as a negative
guard that the Phase 2 mv took effect. Those files are EXCLUDED from
this scan via the explicit ``PRODUCTION_TESTS`` allowlist.

Coverage:
    * AST scan — verify zero ``training.paradigms.az.legacy`` imports
      in the 10 production test files (allows the historical "legacy"
      token to remain in error messages / docstrings).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# Production tests covered by T3c — switched from legacy.* → adapter.
PRODUCTION_TESTS = (
    'training/tests/test_actor_critic_mirror.py',
    'training/tests/test_arena.py',
    'training/tests/test_buffer.py',
    'training/tests/test_config_loader.py',
    'training/tests/test_core_eval_baselines.py',
    'training/tests/test_eval_service_errors.py',
    'training/tests/test_eval_service_matchup.py',
    'training/tests/test_eval_service_schema.py',
    'training/tests/test_inference_server.py',
    'training/tests/test_matchup.py',
)


def _legacy_az_import_names(tree: ast.AST) -> list[str]:
    """Return any ``training.paradigms.az.legacy*`` module names referenced
    by ``import`` / ``from ... import`` statements in the AST.

    String literals containing the word "legacy" (error messages /
    docstrings) are deliberately ignored — this guard targets imports
    only.

    CFR ``training.paradigms.cfr.*`` is OUT OF SCOPE (different
    paradigm; CFR adapter still re-routes via its legacy modules).
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


@pytest.mark.parametrize('rel_path', PRODUCTION_TESTS)
def test_production_test_has_zero_legacy_az_imports(rel_path: str) -> None:
    """AST scan: each in-scope production test has zero ``legacy.*`` AZ imports."""
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    path = repo_root / rel_path
    assert path.is_file(), f'expected production test source file at {path}'
    tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
    offenders = _legacy_az_import_names(tree)
    assert not offenders, (
        f'{rel_path} still imports AZ legacy paths: {offenders} — '
        'should use adapter top-level (training.paradigms.az.*)'
    )


def test_phase2_path_tests_keep_legacy_refs_as_negative_assertions() -> None:
    """Sanity counter-test: Phase 2 path tests intentionally KEEP
    ``training.paradigms.az.legacy`` references as negative assertions
    (they assert ImportError on the mv'd legacy modules). They are
    EXCLUDED from the T3c scan.

    This test verifies at least one Phase 2 path test still references
    the legacy namespace — catches accidental scope creep where someone
    "cleans up" the negative guards and erases the proof that Phase 2
    mv took effect.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    phase2_tests = list((repo_root / 'training' / 'tests').glob('test_az_*phase2_path*.py'))
    assert phase2_tests, 'expected at least one test_az_*phase2_path*.py file in training/tests/'

    legacy_ref_count = 0
    for p in phase2_tests:
        text = p.read_text(encoding='utf-8')
        if 'training.paradigms.az.legacy' in text:
            legacy_ref_count += 1
    assert legacy_ref_count > 0, (
        'No Phase 2 path test references training.paradigms.az.legacy — '
        'the negative ImportError assertions guarding the Phase 2 mv may '
        'have been accidentally erased.'
    )
