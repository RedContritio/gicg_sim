"""Import-topology guard for production tests AZ refs (Phase 3d).

Follow-up to Phase 3c (``test_production_tests_az_refs_phase3c.py``): the
T3c brief listed only 10 specific production tests but grep across all
non-phase2-path tests revealed 11 additional production test files
still referencing ``training.paradigms.az.legacy.*``. Phase 3d sweeps
those 11 to adapter top-level paths per the T2.1-T2.9 + T2.ζ Phase 2
mappings (config / network / buffer / train_step / config_loader all
ship at adapter top-level; OBS constants + ActorCritic + az_losses come
from their canonical ``training.core.*`` sources rather than via
``training.paradigms.az.network`` (which only re-exports Agent +
AgentConfig + AZNetwork + BASIC_HEAD_CLASSES — same pattern T3c used for
``test_actor_critic_mirror.py``).

Phase 2 path tests (``test_az_*phase2_path*.py`` / ``test_az_*phase1*.py``)
intentionally KEEP ``training.paradigms.az.legacy`` references as
negative assertions guarding the Phase 2 mv (they assert ImportError on
mv'd legacy modules). Those files are EXCLUDED from this scan via the
explicit ``PRODUCTION_TESTS`` allowlist.

Coverage:
    * AST scan — verify zero ``training.paradigms.az.legacy`` imports
      in the 11 Phase 3d production test files (string literals
      containing the word "legacy" are deliberately ignored — this
      guard targets imports only).
    * Counter-test — Phase 2 path tests still reference legacy as
      negative assertions (catches accidental scope creep that would
      erase the mv proof).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

# Production tests covered by T3d — switched from legacy.* → adapter.
PRODUCTION_TESTS = (
    'training/tests/test_mcts.py',
    'training/tests/test_mcts_go.py',
    'training/tests/test_network_az_agent.py',
    'training/tests/test_network_az_losses.py',
    'training/tests/test_network_az_trunk.py',
    'training/tests/test_parallel_inference.py',
    'training/tests/test_parallel_pool_deadlock.py',
    'training/tests/test_scenario_sampling.py',
    'training/tests/test_selfplay.py',
    'training/tests/test_train.py',
    'training/tests/test_train_az.py',
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
        'should use adapter top-level (training.paradigms.az.*) or '
        'canonical core sources (training.core.*) per Phase 2 mapping'
    )


def test_phase2_path_tests_keep_legacy_refs_as_negative_assertions() -> None:
    """Sanity counter-test: Phase 2 path tests intentionally KEEP
    ``training.paradigms.az.legacy`` references as negative assertions
    (they assert ImportError on the mv'd legacy modules). They are
    EXCLUDED from the T3d scan.

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
