"""Guard: ``tools.runs.register`` was retired in T-21 of the 2026-05-18
clean-slate redesign (functionality folded into ``tools.runs.train``
per L-1 "no shim"). Any future re-import would silently resurrect the
legacy path and re-create the dual-entry-point ambiguity the redesign
explicitly removed.

Scope: production code only (``tools/`` + ``training/``). Excluded:

- ``.claude/`` — worktree-spawned copies of this very file would
  trigger a false positive (per memory feedback_guard_test_rglob_exclude_claude).
- ``__pycache__/`` — bytecode caches.
- ``docs/``, ``openspec/``, ``CLAUDE.md`` — historical / spec docs are
  out of scope for this guard (T-24 handles ``CLAUDE.md``; openspec
  spec evolution is a separate workflow).
- This file itself — must reference the retired path in prose.
"""

from __future__ import annotations

from pathlib import Path


_NEEDLE = 'tools.runs.register'
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


def test_no_legacy_tools_runs_register_imports():
    """Per T-21 + spec L-1: ``tools.runs.register`` module is gone;
    nothing under ``tools/`` or ``training/`` may import it or print its
    name as a fallback hint. Re-introducing the import would either
    ImportError at runtime or (worse) silently re-create a shim."""
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
        f'``{_NEEDLE}`` (T-21 removed the module per L-1 no-shim policy; '
        f'use tools.runs.train + tools.runs.helpers instead):\n  ' + '\n  '.join(offenders)
    )
