"""Automate the mechanical parts of the OpenSpec 5-step archive SOP.

Spec: ``openspec/specs/openspec-policy/archive-workflow.md`` § "1. 5 步 SOP".

Step coverage:
  - Step 1 (Verify tasks ✓):    AUTOMATED — refuse on any ``- [ ]``.
  - Step 2 (Spec delta merge):  SEMI-MANUAL — operator merges
                                ``changes/<id>/specs/`` into
                                ``openspec/specs/<cap>/spec.md`` AHEAD of
                                this tool, then asserts ``--specs-merged``.
  - Step 3 (行数复检):          DELEGATED to ``check_line_limits`` hook on
                                merged specs (not re-run here).
  - Step 4 (Design 摘要化):     AUTOMATED — verify ``design.md`` exists,
                                ≤ 200 lines, contains ``## Verdict`` header
                                (§ 2.4 template). Summarization is human.
  - Step 5 (git mv):            AUTOMATED — ``git mv`` (or plain ``mv``
                                in ``--no-git`` mode for tests).

CLI:
  python -m tools._meta.openspec_archive --change-id <id> [--specs-merged]
                                         [--dry-run] [--no-commit]
                                         [--no-git] [--root <path>]

Exit codes: 0 on success / dry-run pass; 1 on any gate rejection.

Per archive-workflow.md SHALL 2: every failure raises ``ArchiveRejected``
with explicit reason — no silent fallbacks. The test suite is the live
contract. Tool NEVER edits ``openspec/specs/`` (human review per § 5.2).
"""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Sequence

# File lives at <repo>/tools/_meta/openspec_archive.py → 3 levels up.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# § 2.4 retrospective template requires ``## Verdict`` as the first section.
_VERDICT_HEADER_RE = re.compile(r'^##\s+Verdict\s*$', re.MULTILINE)
# § 1 unchecked / intermediate-state checkbox pattern.
_UNCHECKED_RE = re.compile(r'^\s*-\s*\[([ ~?\-])\]\s+(.*)$')
# Step 4 hard cap from § 2.4.
DESIGN_MAX_LINES = 200


class ArchiveRejected(Exception):
    """Any of the 5 SOP gates rejected the archive request.

    Caller (``main()``) prints to stderr and exits non-zero. Matches
    archive-workflow.md SHALL 2: "任一 step 失败 SHALL exit non-zero".
    """


def _collect_task_files(change_dir: Path) -> List[Path]:
    """Top ``tasks.md`` + ``tasks/*.md``; both forms allowed per § 2.1."""
    files: List[Path] = []
    top = change_dir / 'tasks.md'
    if top.is_file():
        files.append(top)
    sub = change_dir / 'tasks'
    if sub.is_dir():
        files.extend(sorted(p for p in sub.glob('*.md') if p.is_file()))
    return files


def verify_tasks(change_dir: Path) -> None:
    """Step 1: raise if any ``- [ ]`` / ``[~]`` / ``[?]`` / ``[-]`` remain."""
    task_files = _collect_task_files(change_dir)
    if not task_files:
        raise ArchiveRejected(f'no tasks.md (or tasks/) in {change_dir}; § 2.1 requires a task checklist')
    incomplete: List[str] = []
    for tf in task_files:
        for lineno, raw in enumerate(tf.read_text(encoding='utf-8').splitlines(), start=1):
            m = _UNCHECKED_RE.match(raw)
            if m is None:
                continue
            rel = tf.relative_to(change_dir)
            label = m.group(2).strip()[:80] or '<empty>'
            incomplete.append(f'{rel}:{lineno}: [{m.group(1)}] {label}')
    if incomplete:
        details = '\n  '.join(incomplete)
        raise ArchiveRejected(
            f'tasks.md has {len(incomplete)} unchecked / intermediate item(s):\n  {details}\n'
            f'fix: mark every task as [x] before archiving'
        )


def verify_specs_merged(change_dir: Path, specs_merged: bool) -> None:
    """Step 2: refuse if ``specs/`` delta dir present without operator flag.

    Per § 5: Modify needs review, Remove needs grep-and-justify; tool
    cannot safely automate. Operator merges manually then asserts
    ``--specs-merged`` to certify the merge.
    """
    specs_dir = change_dir / 'specs'
    if not specs_dir.is_dir() or specs_merged:
        return
    caps = sorted(p.name for p in specs_dir.iterdir() if p.is_dir())
    cap_list = ', '.join(caps) if caps else '<none>'
    raise ArchiveRejected(
        f'change has unmerged spec delta(s) under {specs_dir.relative_to(change_dir)}/ '
        f'(capabilities: {cap_list}); per § 5, merge them into '
        f'openspec/specs/<cap>/spec.md by hand, then re-run with --specs-merged'
    )


def verify_design(change_dir: Path) -> None:
    """Step 4: design.md exists, ≤ 200 lines, contains ``## Verdict``.

    A ``design/`` subdir may remain (per-subtopic implementation history),
    but a summarized top-level ``design.md`` is required.
    """
    design = change_dir / 'design.md'
    if not design.is_file():
        raise ArchiveRejected(
            f'design.md missing in {change_dir}; § 2.4 requires a ≤ 200-line retrospective at the top level'
        )
    text = design.read_text(encoding='utf-8')
    n_lines = text.count('\n') + (0 if text.endswith('\n') or not text else 1)
    if n_lines > DESIGN_MAX_LINES:
        raise ArchiveRejected(
            f'design.md is {n_lines} lines, exceeds Step 4 cap of {DESIGN_MAX_LINES} '
            f'(§ 2.4); summarize before archiving (move long content into design/)'
        )
    if _VERDICT_HEADER_RE.search(text) is None:
        raise ArchiveRejected(
            'design.md lacks "## Verdict" section header; § 2.4 mandates the '
            'retrospective template (Verdict, What we built, Tradeoffs revisited, '
            'Surprises, Spec delta summary)'
        )


def verify_index_clean(root: Path) -> None:
    """Pre-Step-5: refuse if ``git diff --cached`` is non-empty (else
    ``perform_commit`` would absorb pre-staged unrelated work — repro
    class: sibling-agent commits ``ade04ea`` / ``adc6db2``). Caller MUST
    skip when ``--no-commit`` (operator opts out of the commit step).
    """
    result = subprocess.run(['git', 'diff', '--cached', '--quiet'], cwd=str(root), capture_output=True)
    if result.returncode != 0:
        raise ArchiveRejected(
            'git index has staged changes; commit or stash them before archiving '
            'to avoid absorbing unrelated work into the archive commit '
            '(use --no-commit to bypass this check)'
        )


def perform_move(change_dir: Path, archive_target: Path, root: Path, use_git: bool) -> None:
    """Step 5: move change folder to archive. ``git mv`` unless ``use_git=False``."""
    archive_target.parent.mkdir(parents=True, exist_ok=True)
    if not use_git:
        shutil.move(str(change_dir), str(archive_target))
        return
    try:
        subprocess.run(
            ['git', 'mv', str(change_dir), str(archive_target)],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ArchiveRejected(
            f'git mv {change_dir.relative_to(root)} {archive_target.relative_to(root)} failed: '
            f'{e.stderr.strip() or e.stdout.strip() or "<no output>"}'
        ) from e


def _commit_message(change_id: str) -> str:
    return (
        f'openspec archive: {change_id}\n\n'
        f'Verdict: see openspec/changes/archive/{change_id}/design.md\n\n'
        f'Spec delta merge: performed manually pre-archive (see commit '
        f'history for openspec/specs/<cap>/spec.md edits).\n\n'
        f'5-step SOP per openspec-policy/archive-workflow.md.\n'
    )


def perform_commit(change_id: str, archive_target: Path, root: Path) -> None:
    """Create the archive commit per archive-workflow.md SHALL 3."""
    rel = str(archive_target.relative_to(root))
    try:
        subprocess.run(['git', 'add', rel], cwd=str(root), check=True, capture_output=True, text=True)
        subprocess.run(
            ['git', 'commit', '-m', _commit_message(change_id)],
            cwd=str(root),
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ArchiveRejected(f'commit failed: {e.stderr.strip() or e.stdout.strip() or "<no output>"}') from e


def run(
    *,
    change_id: str,
    root: Path,
    specs_merged: bool = False,
    no_commit: bool = False,
    no_git: bool = False,
    dry_run: bool = False,
) -> int:
    """Run all gates in SHALL 1 order. Returns 0 on success, raises on reject."""
    root = root.resolve()
    change_dir = root / 'openspec' / 'changes' / change_id
    if not change_dir.is_dir():
        raise ArchiveRejected(
            f'change folder not found: openspec/changes/{change_id} (under root {root}); '
            f"active changes only — already-archived changes live under 'changes/archive/'"
        )
    archive_target = root / 'openspec' / 'changes' / 'archive' / change_id

    verify_tasks(change_dir)  # Step 1
    verify_specs_merged(change_dir, specs_merged)  # Step 2 gate
    verify_design(change_dir)  # Step 4 (Step 3 delegated)
    # Pre-Step-5 collision (better error before the mv attempt).
    if archive_target.exists():
        raise ArchiveRejected(
            f'archive target already exists: {archive_target.relative_to(root)}; rename or delete it before retry'
        )
    # Pre-Step-5 working-tree precheck (only when ``perform_commit`` will run).
    if not no_commit:
        verify_index_clean(root)

    if dry_run:
        print(
            f'[dry-run] all gates pass for {change_id}; would move to {archive_target.relative_to(root)}',
            file=sys.stderr,
        )
        return 0

    perform_move(change_dir, archive_target, root, use_git=not no_git)  # Step 5
    if not no_commit:
        perform_commit(change_id, archive_target, root)
    print(f'archived: openspec/changes/archive/{change_id}/', file=sys.stderr)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='python -m tools._meta.openspec_archive',
        description='Automate Steps 1, 4, 5 of the OpenSpec 5-step archive SOP. '
        'Steps 2 (spec delta merge) + 3 (line-limit recheck) remain semi-manual.',
    )
    p.add_argument('--change-id', required=True, help='change id under openspec/changes/<id>/')
    p.add_argument('--root', type=Path, default=REPO_ROOT, help=f'repo root (default: {REPO_ROOT})')
    p.add_argument(
        '--specs-merged',
        action='store_true',
        help='assert that spec delta(s) under changes/<id>/specs/ have been merged '
        'into openspec/specs/<cap>/spec.md by hand (required if a specs/ dir is present)',
    )
    p.add_argument(
        '--dry-run',
        action='store_true',
        help='run Steps 1–4 (verify gates) then stop without touching the filesystem',
    )
    p.add_argument(
        '--no-commit',
        action='store_true',
        help='perform the git mv but skip creating the archive commit',
    )
    p.add_argument(
        '--no-git',
        action='store_true',
        help='use plain shutil.move instead of git mv (test / hermetic mode)',
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        return run(
            change_id=args.change_id,
            root=args.root,
            specs_merged=args.specs_merged,
            no_commit=args.no_commit,
            no_git=args.no_git,
            dry_run=args.dry_run,
        )
    except ArchiveRejected as exc:
        print(f'ARCHIVE REJECTED: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
