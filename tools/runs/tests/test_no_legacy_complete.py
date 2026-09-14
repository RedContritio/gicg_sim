"""Guard: ``tools.runs.complete`` was retired in T-22 of the 2026-05-18
clean-slate redesign (functionality folded into ``tools.runs.train``
Phase C close + ``tools.runs.mark`` for manual finalization, per L-1
"no shim"). Any future re-import would silently resurrect the legacy
CLI and re-create the dual-write ambiguity (train auto-close vs
post-train complete CLI) the redesign explicitly removed.

Scope: production code only (``tools/`` + ``training/``). Excluded:

- ``.claude/`` — worktree-spawned copies of this file would trigger a
  false positive.
- ``__pycache__/`` — bytecode caches.
- ``docs/``, ``openspec/``, ``CLAUDE.md`` — historical / spec docs are
  out of scope for this guard (T-24 handles ``CLAUDE.md``; openspec
  spec evolution is a separate workflow).
- This file itself — must reference the retired path in prose.
"""

from __future__ import annotations

from pathlib import Path


_NEEDLE = 'tools.runs.complete'
_REPO_ROOT = Path(__file__).resolve().parents[3]
_ROOTS = ('tools', 'training')
_SELF = Path(__file__).resolve()


def _iter_py_files():
    for rel in _ROOTS:
        root = _REPO_ROOT / rel
        if not root.is_dir():
            continue
        for f in root.rglob('*.py'):
            s = str(f)
            if '/.claude/' in s or '__pycache__' in s:
                continue
            if f.resolve() == _SELF:
                continue
            yield f


def test_no_legacy_tools_runs_complete_imports():
    """Per T-22 + spec L-1: ``tools.runs.complete`` module is gone;
    nothing under ``tools/`` or ``training/`` may import it or print its
    name as a fallback hint. Re-introducing the import would either
    ImportError at runtime or (worse) silently re-create a shim parallel
    to ``tools.runs.train`` Phase C close + ``tools.runs.mark``."""
    offenders = []
    for f in _iter_py_files():
        try:
            text = f.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        if _NEEDLE in text:
            offenders.append(str(f.relative_to(_REPO_ROOT)))
    assert not offenders, (
        f'Found {len(offenders)} file(s) still referencing retired '
        f'``{_NEEDLE}`` (T-22 removed the module per L-1 no-shim policy; '
        f'use tools.runs.train Phase C close + tools.runs.mark instead):\n  ' + '\n  '.join(offenders)
    )
