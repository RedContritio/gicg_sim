"""Enforce per-file line-count + byte-count limits.

Rules (fail if EITHER line OR byte threshold exceeded). First matching
rule wins, so order is most-specific → most-general within each section.

Code files:
  - Python test files (``**/tests/`` or ``test_*.py``):  500 lines, no byte cap
  - Other Python / Go files:                              300 lines, no byte cap

Repo-root docs:
  - ``CLAUDE.md`` (injected into every LLM context):      200 lines / 30 KB

OpenSpec artifacts (REJECT / hard fail thresholds, see
``openspec/specs/openspec-policy/thresholds.md`` for the WARNING /
MUST-SPLIT story; hook only enforces hard fail because git commit has
no warning channel):
  - ``openspec/project.md``:                              350 lines / 50 KB
  - ``openspec/specs/<cap>/spec.md`` (capability index):  350 lines / 50 KB
  - ``openspec/specs/<cap>/<subtopic>.md``:               500 lines / 50 KB
  - ``openspec/changes/<chg>/proposal.md``:               350 lines / 50 KB
  - ``openspec/changes/<chg>/design.md``:                 600 lines / 50 KB
  - ``openspec/changes/<chg>/design/<file>.md``:          500 lines / 50 KB
  - ``openspec/changes/<chg>/tasks.md``:                  600 lines / 50 KB
  - ``openspec/changes/<chg>/tasks/<file>.md``:           500 lines / 50 KB
  - ``openspec/changes/<chg>/specs/.../spec.md`` (delta): 350 lines / 50 KB

Other docs:
  - ``docs/now.md`` (LIVE 状态快照,若存在):              350 lines / 30 KB
  - Other ``docs/**/*.md``:                               500 lines / 50 KB

Invoked as a pre-commit hook to gate staged files, or as a standalone
audit to list every violator in the repo.

Modes:
  python -m tools._meta.check_line_limits               # audit every tracked file
  python -m tools._meta.check_line_limits --staged      # only git-staged files
  python -m tools._meta.check_line_limits --paths a.py  # explicit paths

Exit code: 0 if every file is within its limit, 1 otherwise.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Optional, Tuple

# File lives at <repo>/tools/_meta/check_line_limits.py → 3 levels up.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# (line_limit, byte_limit) — None means no cap on that axis.
RULES: List[Tuple[str, Tuple[int, Optional[int]]]] = [
    # Order matters: first matching rule wins. Most-specific first.
    ('CLAUDE.md_exact', (200, 30 * 1024)),
    ('py_test', (500, None)),
    ('py_prod', (300, None)),
    ('go', (300, None)),
    # OpenSpec artifacts — hard-fail thresholds from
    # openspec/specs/openspec-policy/thresholds.md REJECT column.
    ('openspec_project', (350, 50 * 1024)),
    ('openspec_spec_main', (350, 50 * 1024)),
    ('openspec_spec_subtopic', (500, 50 * 1024)),
    ('openspec_change_proposal', (350, 50 * 1024)),
    ('openspec_change_design_top', (600, 50 * 1024)),
    ('openspec_change_design_sub', (500, 50 * 1024)),
    ('openspec_change_tasks_top', (600, 50 * 1024)),
    ('openspec_change_tasks_sub', (500, 50 * 1024)),
    ('openspec_change_spec_delta', (350, 50 * 1024)),
    # docs/now.md — LIVE 状态快照,与 CLAUDE.md 同字节档(30 KB)。
    ('docs_now', (350, 30 * 1024)),
    ('docs_md', (500, 50 * 1024)),
]


def _openspec_rule(parts: tuple, name: str) -> Optional[str]:
    """Classify ``openspec/...`` markdown paths into a RULES key.

    ``parts`` is ``rel.parts`` (always starts with ``'openspec'``);
    ``name`` is ``rel.name``. Returns None for paths outside the
    enforced subtree (e.g. ``openspec/AGENTS.md``) so the caller falls
    through to default handling.
    """
    # openspec/project.md
    if len(parts) == 2 and parts[1] == 'project.md':
        return 'openspec_project'
    if len(parts) < 3:
        return None
    subtree = parts[1]
    # openspec/specs/<cap>/...
    if subtree == 'specs':
        # parts: ('openspec', 'specs', '<cap>', ...rest..., '<file>.md')
        if len(parts) == 4 and name == 'spec.md':
            return 'openspec_spec_main'
        if len(parts) >= 4:
            return 'openspec_spec_subtopic'
        return None
    # openspec/changes/<chg>/...
    if subtree == 'changes':
        if len(parts) < 4:
            return None
        # parts[2] = change name; parts[3:] = path inside the change.
        rest = parts[3:]
        if len(rest) == 1:
            f = rest[0]
            if f == 'proposal.md':
                return 'openspec_change_proposal'
            if f == 'design.md':
                return 'openspec_change_design_top'
            if f == 'tasks.md':
                return 'openspec_change_tasks_top'
            return None
        # Nested: design/<x>.md, tasks/<x>.md, specs/<cap>/.../spec.md
        head = rest[0]
        if head == 'design':
            return 'openspec_change_design_sub'
        if head == 'tasks':
            return 'openspec_change_tasks_sub'
        if head == 'specs' and rest[-1] == 'spec.md':
            return 'openspec_change_spec_delta'
        return None
    return None


def _rule_for(path: Path) -> Optional[Tuple[int, Optional[int]]]:
    """Resolve the (line, byte) limit pair for ``path`` or None if
    the file is outside the enforcement scope (e.g. JSON, shell)."""
    rel = path.relative_to(REPO_ROOT) if path.is_absolute() else path
    name = rel.name
    parts = rel.parts
    rules_dict = dict(RULES)
    if name == 'CLAUDE.md' and '/' not in str(rel):
        return rules_dict['CLAUDE.md_exact']
    if rel.suffix == '.py':
        is_test = 'tests' in parts or name.startswith('test_') or name.endswith('_test.py')
        return rules_dict['py_test' if is_test else 'py_prod']
    if rel.suffix == '.go':
        return rules_dict['go']
    if parts and parts[0] == 'openspec' and rel.suffix == '.md':
        key = _openspec_rule(parts, name)
        if key is not None:
            return rules_dict[key]
        return None
    if parts and parts[0] == 'docs' and rel.suffix == '.md':
        # docs/now.md gets its own tighter byte cap (30 KB).
        if len(parts) == 2 and name == 'now.md':
            return rules_dict['docs_now']
        return rules_dict['docs_md']
    return None


def _measure(path: Path) -> Tuple[int, int]:
    """Return (line_count, byte_count)."""
    with path.open('rb') as f:
        data = f.read()
    return data.count(b'\n') + (0 if data.endswith(b'\n') or not data else 1), len(data)


def _staged_files() -> List[Path]:
    out = subprocess.check_output(
        ['git', 'diff', '--cached', '--name-only', '--diff-filter=ACM'],
        cwd=REPO_ROOT,
        text=True,
    )
    paths: List[Path] = []
    for name in out.splitlines():
        p = REPO_ROOT / name
        if p.exists():
            paths.append(p)
    return paths


def _all_tracked() -> List[Path]:
    out = subprocess.check_output(
        ['git', 'ls-files'],
        cwd=REPO_ROOT,
        text=True,
    )
    return [REPO_ROOT / name for name in out.splitlines()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        '--staged',
        action='store_true',
        help='check git-staged files only (pre-commit mode)',
    )
    ap.add_argument('--paths', nargs='+', type=Path, help='check explicit paths')
    args = ap.parse_args()

    if args.paths:
        files = [p.resolve() for p in args.paths]
    elif args.staged:
        files = _staged_files()
    else:
        files = _all_tracked()

    violations: List[tuple] = []
    for path in files:
        rule = _rule_for(path)
        if rule is None:
            continue
        line_limit, byte_limit = rule
        try:
            n_lines, n_bytes = _measure(path)
        except FileNotFoundError:
            continue
        reason = None
        if n_lines > line_limit:
            reason = f'{n_lines} lines > {line_limit}'
        elif byte_limit is not None and n_bytes > byte_limit:
            reason = f'{n_bytes} bytes > {byte_limit}'
        if reason:
            violations.append((reason, path))

    if not violations:
        return 0

    print(
        f'line-limit violations ({len(violations)} file{"s" if len(violations) != 1 else ""}):',
        file=sys.stderr,
    )
    for reason, path in violations:
        try:
            display = path.relative_to(REPO_ROOT)
        except ValueError:
            display = path
        print(f'  {reason}   {display}', file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
