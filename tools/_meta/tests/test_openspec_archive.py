"""Tests for :mod:`tools._meta.openspec_archive`.

Contract under test
-------------------
``openspec_archive`` mechanizes Steps 1, 4, 5 of the 5-step archive SOP
defined in ``openspec/specs/openspec-policy/archive-workflow.md``:

  Step 1: Verify ``tasks.md`` (or ``tasks/*.md``) has zero ``- [ ]``
          unchecked items.
  Step 4: Verify ``design.md`` is ≤200 lines and contains a
          retrospective section header (``## Verdict``).
  Step 5: ``git mv openspec/changes/<id>/ → openspec/changes/archive/<id>/``
          (or ``mv`` in ``--no-git`` mode for hermetic tests).

Steps 2 (spec delta merge) and 3 (line-limit recheck post-merge) are
semi-manual — operators stage them ahead of time. The tool refuses to
archive when ``changes/<id>/specs/`` still exists AND ``--specs-merged``
is not asserted (gating Step 2). Step 3 is delegated to the existing
``check_line_limits`` pre-commit hook on the merged specs.

Happy-path golden test
~~~~~~~~~~~~~~~~~~~~~~
Reverse-engineer a "ready-to-archive" fixture from an actually-archived
change. After running the tool the state byte-equals the archive layout:
the change folder moved, no orphans left, no spec damage.

Safety guards
~~~~~~~~~~~~~
- Refuses when tasks.md has any ``- [ ]``.
- Refuses when design.md is missing or >200 lines or lacks ``## Verdict``.
- Refuses when ``changes/<id>/specs/`` exists without ``--specs-merged``.
- Refuses when ``changes/archive/<id>/`` already exists.

Per :mod:`CLAUDE.md`: 不接受静默回退;契约违反 SHALL raise/exit-non-zero.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools._meta import openspec_archive


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write(p: Path, body: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding='utf-8')


_TASKS_DONE = """# foo-change — tasks

- [x] T1: design schema
- [x] T2: implement
- [x] T3: tests
"""

_TASKS_INCOMPLETE = """# foo-change — tasks

- [x] T1: design schema
- [ ] T2: implement
- [x] T3: tests
"""

_DESIGN_OK = """---
last_updated: 2026-05-16
status: ARCHIVED
schema_version: 0
change_id: foo-change
---

# Design Retrospective — foo-change

## Verdict

**Success**: shipped without issue.

## What we built

- single thing

## Tradeoffs revisited

- predicted X, observed X (consistent)

## Surprises

None.

## Spec delta summary

- foo capability: +2 SHALL
"""

_DESIGN_NO_VERDICT = """# Design — foo-change

## Background

Long story.

## Plan

Bullets.
"""

_PROPOSAL = """---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
change_id: foo-change
---

# foo-change — why

Single paragraph.
"""


def _make_ready_change(root: Path, change_id: str = 'foo-change') -> Path:
    """Build a minimal change folder that satisfies Steps 1 + 4.

    No ``specs/`` delta dir (Step 2 trivially passes). Caller may add
    one and pass ``--specs-merged`` separately.
    """
    chg = root / 'openspec' / 'changes' / change_id
    _write(chg / 'tasks.md', _TASKS_DONE)
    _write(chg / 'design.md', _DESIGN_OK)
    _write(chg / 'proposal.md', _PROPOSAL)
    return chg


def _make_oversized_design() -> str:
    """Design body with >200 lines (still has Verdict)."""
    header = '# foo\n\n## Verdict\n\nok\n'
    filler = '\n'.join(f'line {i}' for i in range(220))
    return header + filler + '\n'


# ---------------------------------------------------------------------------
# Happy-path golden test
# ---------------------------------------------------------------------------


def test_archive_happy_path_moves_folder(tmp_path: Path) -> None:
    """A complete change folder is moved to ``archive/<id>/`` intact."""
    chg = _make_ready_change(tmp_path)
    archive_target = tmp_path / 'openspec' / 'changes' / 'archive' / 'foo-change'

    rc = openspec_archive.run(
        change_id='foo-change',
        root=tmp_path,
        specs_merged=True,  # no specs dir present, trivially fine
        no_commit=True,
        no_git=True,  # hermetic — don't touch a parent git repo
    )

    assert rc == 0, 'expected exit 0 on happy path'
    assert not chg.exists(), 'source change folder must be gone after archive'
    assert archive_target.is_dir(), f'archive folder missing: {archive_target}'
    # Files moved intact (byte-identical via read).
    assert (archive_target / 'tasks.md').read_text(encoding='utf-8') == _TASKS_DONE
    assert (archive_target / 'design.md').read_text(encoding='utf-8') == _DESIGN_OK
    assert (archive_target / 'proposal.md').read_text(encoding='utf-8') == _PROPOSAL


def test_archive_dry_run_does_not_move(tmp_path: Path) -> None:
    """``--dry-run`` mode reports OK but leaves the source folder in place."""
    chg = _make_ready_change(tmp_path)
    archive_target = tmp_path / 'openspec' / 'changes' / 'archive' / 'foo-change'

    rc = openspec_archive.run(
        change_id='foo-change',
        root=tmp_path,
        specs_merged=True,
        no_commit=True,
        no_git=True,
        dry_run=True,
    )

    assert rc == 0
    assert chg.exists(), 'dry-run must NOT move the change'
    assert not archive_target.exists()


# ---------------------------------------------------------------------------
# Safety guards (Step 1)
# ---------------------------------------------------------------------------


def test_archive_refuses_when_tasks_incomplete(tmp_path: Path) -> None:
    """Step 1 SHALL exit non-zero if any ``- [ ]`` checkbox remains."""
    chg = _make_ready_change(tmp_path)
    (chg / 'tasks.md').write_text(_TASKS_INCOMPLETE, encoding='utf-8')

    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    msg = str(exc.value)
    assert 'tasks.md' in msg
    assert 'T2' in msg, f'expected unchecked task T2 in error, got: {msg}'
    # Source not moved.
    assert chg.exists()


def test_archive_scans_tasks_subdir_when_no_top_tasks_md(tmp_path: Path) -> None:
    """When ``tasks/`` subdir is used instead of ``tasks.md``, scan it too."""
    chg = _make_ready_change(tmp_path)
    (chg / 'tasks.md').unlink()
    _write(chg / 'tasks' / 'phase1.md', '- [x] one\n- [x] two\n')
    _write(chg / 'tasks' / 'phase2.md', '- [x] three\n- [ ] four\n')

    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    assert 'phase2.md' in str(exc.value)


# ---------------------------------------------------------------------------
# Safety guards (Step 4)
# ---------------------------------------------------------------------------


def test_archive_refuses_when_design_missing(tmp_path: Path) -> None:
    chg = _make_ready_change(tmp_path)
    (chg / 'design.md').unlink()
    # design/ subdir alternative not provided either.
    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    assert 'design' in str(exc.value).lower()


def test_archive_refuses_when_design_oversized(tmp_path: Path) -> None:
    chg = _make_ready_change(tmp_path)
    (chg / 'design.md').write_text(_make_oversized_design(), encoding='utf-8')
    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    msg = str(exc.value)
    assert '200' in msg, f'expected 200-line threshold in message: {msg}'


def test_archive_refuses_when_design_lacks_verdict(tmp_path: Path) -> None:
    chg = _make_ready_change(tmp_path)
    (chg / 'design.md').write_text(_DESIGN_NO_VERDICT, encoding='utf-8')
    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    assert 'Verdict' in str(exc.value)


# ---------------------------------------------------------------------------
# Safety guards (Step 2)
# ---------------------------------------------------------------------------


def test_archive_refuses_when_specs_unmerged(tmp_path: Path) -> None:
    """``changes/<id>/specs/`` exists ⇒ require --specs-merged assertion."""
    chg = _make_ready_change(tmp_path)
    _write(chg / 'specs' / 'foo' / 'spec.md', '## ADDED\n\n- [x] thing\n')
    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=False,
            no_commit=True,
            no_git=True,
        )
    msg = str(exc.value)
    assert 'specs' in msg.lower() and 'merge' in msg.lower()


def test_archive_accepts_specs_dir_when_merged_flag_asserted(tmp_path: Path) -> None:
    chg = _make_ready_change(tmp_path)
    _write(chg / 'specs' / 'foo' / 'spec.md', '## ADDED\n\n- [x] thing\n')
    rc = openspec_archive.run(
        change_id='foo-change',
        root=tmp_path,
        specs_merged=True,
        no_commit=True,
        no_git=True,
    )
    assert rc == 0
    archive_target = tmp_path / 'openspec' / 'changes' / 'archive' / 'foo-change'
    assert (archive_target / 'specs' / 'foo' / 'spec.md').exists(), 'specs/ must move along'
    assert not chg.exists()


# ---------------------------------------------------------------------------
# Safety guards (Step 5)
# ---------------------------------------------------------------------------


def test_archive_refuses_when_target_already_exists(tmp_path: Path) -> None:
    chg = _make_ready_change(tmp_path)
    target = tmp_path / 'openspec' / 'changes' / 'archive' / 'foo-change'
    target.mkdir(parents=True)
    (target / 'placeholder').write_text('preexisting\n', encoding='utf-8')

    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    assert 'archive' in str(exc.value).lower() and 'exists' in str(exc.value).lower()
    assert chg.exists(), 'source not moved on Step 5 failure'


def test_archive_refuses_when_change_id_missing(tmp_path: Path) -> None:
    # No change folder created at all.
    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='ghost',
            root=tmp_path,
            specs_merged=True,
            no_commit=True,
            no_git=True,
        )
    assert 'ghost' in str(exc.value) or 'not found' in str(exc.value).lower()


# ---------------------------------------------------------------------------
# CLI smoke
# ---------------------------------------------------------------------------


def test_cli_main_returns_zero_on_happy_path(tmp_path: Path) -> None:
    """``main()`` driven via argv parses and runs end-to-end."""
    _make_ready_change(tmp_path)
    rc = openspec_archive.main(
        [
            '--change-id',
            'foo-change',
            '--root',
            str(tmp_path),
            '--specs-merged',
            '--no-commit',
            '--no-git',
        ]
    )
    assert rc == 0
    assert (tmp_path / 'openspec' / 'changes' / 'archive' / 'foo-change').is_dir()


def test_cli_main_returns_nonzero_on_rejection(tmp_path: Path) -> None:
    chg = _make_ready_change(tmp_path)
    (chg / 'tasks.md').write_text(_TASKS_INCOMPLETE, encoding='utf-8')
    rc = openspec_archive.main(
        [
            '--change-id',
            'foo-change',
            '--root',
            str(tmp_path),
            '--specs-merged',
            '--no-commit',
            '--no-git',
        ]
    )
    assert rc != 0


def test_cli_help_exits_zero() -> None:
    """``python -m tools._meta.openspec_archive --help`` works."""
    result = subprocess.run(
        [sys.executable, '-m', 'tools._meta.openspec_archive', '--help'],
        cwd=str(Path(__file__).resolve().parents[3]),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f'help exit nonzero: {result.stderr}'
    assert '--change-id' in result.stdout


# ---------------------------------------------------------------------------
# Safety guards (working-tree precheck — Important: avoid absorbing pre-staged
# unrelated changes into the archive commit; same failure class as the
# sibling-agent race that contaminated commits ade04ea / adc6db2)
# ---------------------------------------------------------------------------


def _init_git_repo(root: Path) -> None:
    """Init a minimal hermetic git repo (no signing, local-only identity)."""
    subprocess.run(['git', 'init', '-q', '-b', 'main'], cwd=str(root), check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=str(root), check=True)
    subprocess.run(['git', 'config', 'user.name', 'test'], cwd=str(root), check=True)
    subprocess.run(['git', 'config', 'commit.gpgsign', 'false'], cwd=str(root), check=True)


def test_archive_refuses_when_index_dirty(tmp_path: Path) -> None:
    """Important: ``git commit`` absorbs pre-staged unrelated changes.

    Repro: stage an unrelated file before invoking the archive tool. The
    precheck SHALL reject before ``perform_move`` runs so the dirty index
    can never bleed into the archive commit. Also verifies the
    ``--no-commit`` bypass keeps working when the operator opts out of
    the commit step explicitly.
    """
    _init_git_repo(tmp_path)
    # Seed an initial commit so we have a HEAD ref to diff against.
    (tmp_path / 'README.md').write_text('seed\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'README.md'], cwd=str(tmp_path), check=True)
    subprocess.run(['git', 'commit', '-q', '-m', 'seed'], cwd=str(tmp_path), check=True)

    chg = _make_ready_change(tmp_path)
    # Pre-stage an unrelated file — simulates operator forgetting to commit
    # WIP before running the archive tool.
    unrelated = tmp_path / 'unrelated.txt'
    unrelated.write_text('wip work that does NOT belong in archive commit\n', encoding='utf-8')
    subprocess.run(['git', 'add', 'unrelated.txt'], cwd=str(tmp_path), check=True)

    # Positive case: commit=True (default), precheck SHALL fire.
    with pytest.raises(openspec_archive.ArchiveRejected) as exc:
        openspec_archive.run(
            change_id='foo-change',
            root=tmp_path,
            specs_merged=True,
            no_commit=False,  # commit path → precheck must run
            no_git=True,  # don't require git mv to succeed; isolate the gate
        )
    msg = str(exc.value).lower()
    assert 'staged' in msg or 'index' in msg, f'expected staged-changes message, got: {exc.value}'
    # Source folder not moved — fail-fast before perform_move.
    assert chg.exists(), 'precheck must reject before perform_move runs'

    # Bypass case: --no-commit asserted, gate is skipped (operator opts out
    # of the commit step, takes responsibility for the dirty index).
    rc = openspec_archive.run(
        change_id='foo-change',
        root=tmp_path,
        specs_merged=True,
        no_commit=True,  # bypass
        no_git=True,
    )
    assert rc == 0
    archive_target = tmp_path / 'openspec' / 'changes' / 'archive' / 'foo-change'
    assert archive_target.is_dir(), '--no-commit bypass should let the move proceed'
