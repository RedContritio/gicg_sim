"""Verify OpenSpec index integrity.

Enforces invariants from ``openspec/specs/openspec-policy/spec.md``
SHALL 6 + 11 + 12 (索引强制 / 行数 enforcement / 索引 enforcement):

  R1 (主 spec.md 索引完整): For each ``openspec/specs/<cap>/spec.md``
     the ``## Subtopics`` section SHALL list every sibling ``.md`` in the
     same directory (except ``spec.md`` itself).
  R2 (索引文件存在): Every ``./<file>.md`` listed in ``## Subtopics``
     SHALL exist on disk in the same directory.
  R3 (Change 三件套): Each ``openspec/changes/<id>/`` (and
     ``openspec/changes/archive/<id>/``) SHALL contain ``proposal.md``,
     and either ``design.md`` or ``design/`` subdir, and either
     ``tasks.md`` or ``tasks/`` subdir.
  R5 (Placeholder 豁免): Only ``openspec/specs/<cap>/spec.md`` files are
     scanned as "main spec"; subtopic files are NOT scanned, so any
     ``./<file>.md`` placeholders inside them (e.g. ``file-layout.md``'s
     `## Subtopics` template in section 5.1) are naturally exempt.
     Additionally ``./<meta>.md`` / ``./[META].md`` links inside a main
     ``spec.md`` are recognised as templates and NOT counted as dead
     links by R2 (see ``_PLACEHOLDER_TOKEN_RE``).

R4 (tasks/design subdir index) is intentionally not implemented — it was
a nice-to-have warning per the task spec.

CLI modes:
  python -m tools._meta.check_openspec_indices                  # full tree
  python -m tools._meta.check_openspec_indices PATH [PATH ...]  # specific paths
  python -m tools._meta.check_openspec_indices --staged         # staged only

Exit code: 0 if all checks pass, 1 otherwise. Violations print one per
line to stderr as ``<path>[:<line>]: <message>``.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

# File lives at <repo>/tools/_meta/check_openspec_indices.py → 3 levels up.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Header matches "## Subtopics", "## 4. Subtopics", "## 子主题" etc.
_SUBTOPICS_HEADER_RE = re.compile(r'^##\s+(?:\d+\.\s+)?(?:Subtopics|子主题)\s*$')
_ANY_H2_RE = re.compile(r'^##\s+')
# Bullet with link: "- [label](./file.md) …". Captures bare filename.
_LINK_RE = re.compile(r'^\s*-\s*\[([^\]]+)\]\(\./([^)#]+\.md)\)')
_FENCE_RE = re.compile(r'^(?:```|~~~)')
# Placeholder meta-var inside a link target (R5): ``./<file>.md`` /
# ``./[ID].md``. Kebab-case token in angle / square brackets.
_PLACEHOLDER_TOKEN_RE = re.compile(r'[<\[][A-Za-z0-9_\-]+[>\]]')


def _is_placeholder_target(target: str) -> bool:
    return bool(_PLACEHOLDER_TOKEN_RE.search(target))


@dataclass(frozen=True)
class Violation:
    """A single rule violation. ``line`` is 1-based or None if unknown."""

    file: str
    line: Optional[int]
    message: str

    def format(self) -> str:
        loc = f'{self.file}:{self.line}' if self.line else self.file
        return f'{loc}: {self.message}'


def parse_subtopics(spec_md: Path) -> Tuple[List[Tuple[str, int]], Optional[int]]:
    """Parse ``## Subtopics`` (or ``## 子主题``) section of ``spec_md``.

    Returns ``(entries, header_line)`` where ``entries`` lists
    ``(target_filename, line_number)`` tuples for every link bullet
    inside the section. ``header_line`` is the 1-based line of the
    header, or None if absent. Bullets inside fenced code blocks are
    skipped (defensive).
    """
    entries: List[Tuple[str, int]] = []
    header_line: Optional[int] = None
    in_section = False
    in_fence = False
    text = spec_md.read_text(encoding='utf-8')
    for idx, raw in enumerate(text.splitlines(), start=1):
        if _FENCE_RE.match(raw):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if _SUBTOPICS_HEADER_RE.match(raw):
            in_section = True
            header_line = idx
            continue
        if in_section and _ANY_H2_RE.match(raw):
            in_section = False
            continue
        if not in_section:
            continue
        m = _LINK_RE.match(raw)
        if m:
            entries.append((m.group(2), idx))
    return entries, header_line


def _sibling_md_files(spec_md: Path) -> Set[str]:
    """Return basenames of sibling ``.md`` files (excluding spec.md and hidden)."""
    return {p.name for p in spec_md.parent.glob('*.md') if p != spec_md and not p.name.startswith('.')}


def check_capability_indices(spec_md: Path) -> List[Violation]:
    """Validate R1 + R2 for one capability ``spec.md`` (R5 skips placeholders)."""
    violations: List[Violation] = []
    rel = _rel(spec_md)
    entries, header_line = parse_subtopics(spec_md)
    listed = {target for target, _ in entries if not _is_placeholder_target(target)}
    siblings = _sibling_md_files(spec_md)

    # R1: every sibling .md must appear in Subtopics.
    for fname in sorted(siblings - listed):
        msg = (
            f"missing Subtopics index entry for './{fname}' "
            f'(exists in directory but not listed); '
            f'add `- [Title](./{fname}) — <description>` to ## Subtopics'
        )
        violations.append(Violation(rel, header_line, msg))

    # R2: every listed link must exist as a file.
    for target, line in entries:
        if _is_placeholder_target(target):
            continue
        if target in siblings:
            continue
        if target == spec_md.name:
            msg = f"Subtopics entry './{target}' is the spec.md itself; self-references are not allowed"
        else:
            msg = (
                f"dead Subtopics link './{target}' (listed in ## Subtopics but "
                f"no such file in directory); remove the entry or create '{target}'"
            )
        violations.append(Violation(rel, line, msg))

    return violations


def check_change_triplet(change_dir: Path) -> List[Violation]:
    """Validate R3: change dir contains proposal + design + tasks."""
    rel = _rel(change_dir) + '/'
    violations: List[Violation] = []
    if not (change_dir / 'proposal.md').exists():
        violations.append(Violation(rel, None, "missing required artifact 'proposal.md'"))
    if not (change_dir / 'design.md').exists() and not (change_dir / 'design').is_dir():
        violations.append(Violation(rel, None, "missing required artifact 'design.md' or 'design/' directory"))
    if not (change_dir / 'tasks.md').exists() and not (change_dir / 'tasks').is_dir():
        violations.append(Violation(rel, None, "missing required artifact 'tasks.md' or 'tasks/' directory"))
    return violations


def find_main_spec_files(openspec_root: Path) -> List[Path]:
    """Yield every ``openspec/specs/<capability>/spec.md`` under root."""
    specs_dir = openspec_root / 'specs'
    if not specs_dir.is_dir():
        return []
    out: List[Path] = []
    for cap_dir in sorted(specs_dir.iterdir()):
        if cap_dir.is_dir() and (cap_dir / 'spec.md').is_file():
            out.append(cap_dir / 'spec.md')
    return out


def find_change_dirs(openspec_root: Path) -> List[Path]:
    """Yield change dirs: ``changes/<id>/`` and ``changes/archive/<id>/``."""
    changes_dir = openspec_root / 'changes'
    if not changes_dir.is_dir():
        return []
    out: List[Path] = []
    for entry in sorted(changes_dir.iterdir()):
        if not entry.is_dir():
            continue
        if entry.name == 'archive':
            out.extend(sub for sub in sorted(entry.iterdir()) if sub.is_dir())
        else:
            out.append(entry)
    return out


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def check_full_tree(openspec_root: Path) -> List[Violation]:
    violations: List[Violation] = []
    for spec_md in find_main_spec_files(openspec_root):
        violations.extend(check_capability_indices(spec_md))
    for change_dir in find_change_dirs(openspec_root):
        violations.extend(check_change_triplet(change_dir))
    return violations


def _is_main_spec(path: Path) -> bool:
    """True iff ``path`` is an ``openspec/specs/<cap>/spec.md``."""
    try:
        parts = path.resolve().relative_to(REPO_ROOT).parts
    except ValueError:
        return False
    return len(parts) == 4 and parts[0] == 'openspec' and parts[1] == 'specs' and parts[3] == 'spec.md'


def _change_dir_for(path: Path) -> Optional[Path]:
    """If ``path`` lives inside a change dir, return that change dir.

    Handles both ``openspec/changes/<id>/...`` and
    ``openspec/changes/archive/<id>/...``.
    """
    try:
        parts = path.resolve().relative_to(REPO_ROOT).parts
    except ValueError:
        return None
    if len(parts) < 3 or parts[0] != 'openspec' or parts[1] != 'changes':
        return None
    if parts[2] == 'archive':
        if len(parts) < 4:
            return None
        return REPO_ROOT / 'openspec' / 'changes' / 'archive' / parts[3]
    return REPO_ROOT / 'openspec' / 'changes' / parts[2]


def check_paths(paths: Iterable[Path]) -> List[Violation]:
    """Check a specific set of paths.

    For each path: if it's a capability spec.md → R1+R2; if it's inside
    a change dir → R3 on that change dir (deduplicated); else ignored.
    """
    violations: List[Violation] = []
    seen_changes: Set[Path] = set()
    seen_specs: Set[Path] = set()
    for p in paths:
        if _is_main_spec(p) and p.exists() and p not in seen_specs:
            seen_specs.add(p)
            violations.extend(check_capability_indices(p))
            continue
        change_dir = _change_dir_for(p)
        if change_dir is not None and change_dir.is_dir() and change_dir not in seen_changes:
            seen_changes.add(change_dir)
            violations.extend(check_change_triplet(change_dir))
    return violations


def _staged_files() -> List[Path]:
    out = subprocess.check_output(
        ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR'],
        cwd=REPO_ROOT,
        text=True,
    )
    return [REPO_ROOT / name for name in out.splitlines() if name.startswith('openspec/')]


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description='Verify OpenSpec index integrity (R1+R2+R3).')
    ap.add_argument('paths', nargs='*', type=Path, help='paths to check (default: full openspec/ tree)')
    ap.add_argument('--staged', action='store_true', help='check only git-staged openspec/ files')
    ap.add_argument(
        '--root',
        type=Path,
        default=REPO_ROOT / 'openspec',
        help='openspec/ root to scan (default: <repo>/openspec)',
    )
    args = ap.parse_args(argv)

    if args.staged:
        violations = check_paths(_staged_files())
    elif args.paths:
        violations = check_paths([p.resolve() for p in args.paths])
    else:
        violations = check_full_tree(args.root)

    if not violations:
        return 0
    print(f'openspec index violations ({len(violations)}):', file=sys.stderr)
    for v in violations:
        print(v.format(), file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
