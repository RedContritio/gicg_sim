"""Guard: ``tools/run.py`` (the legacy unified train entry) was retired
in T-23 of the 2026-05-18 ``tools/runs/`` clean-slate redesign — its
paradigm-dispatch + cfg-load + run_pipeline body was migrated
verbatim into ``tools.runs._train.dispatch.run_paradigm_train`` by
T-11, and the public entry shell is now ``tools.runs.train`` (spec
§Architecture CRIT-X-1 行 28-32 method A "完整迁移,no thin shim";
§File structure Delete 行 573-577 L-1).

Re-adding either ``tools/run.py`` or any ``python -m tools.run``
invocation under production code would silently resurrect the
dual-entry-point ambiguity the redesign explicitly removed.

Two needles checked under ``tools/`` + ``training/``:

- ``python -m tools.run`` — boundary form for shell-invoked subprocess
  / docstring / multi-seed launcher references. Matches the spec verify
  command ``git grep -E 'python -m tools\\.run( |$)'`` exactly.
- ``from tools.run`` / ``import tools.run`` — defensive guard against a
  future re-import (the module file is deleted; any such import would
  ImportError at runtime, but the static check fails fast at lint
  time and pins the deletion intent).

Scope: production code only (``tools/`` + ``training/``). Excluded:

- ``.claude/`` — worktree-spawned copies of this file would trigger a
  false positive.
- ``__pycache__/`` — bytecode caches.
- ``docs/``, ``openspec/``, ``CLAUDE.md`` — historical / spec docs
  legitimately reference the retired path; out of scope for this
  guard (T-24 handles ``CLAUDE.md`` rewrites; openspec spec evolution
  is a separate workflow).
- This file itself — must reference the retired path in prose.
"""

from __future__ import annotations

import re
from pathlib import Path


# Boundary regex — matches ``python -m tools.run`` followed by space or
# EOL (the exact spec verify form), AND the bare ``tools.run`` form
# when not followed by ``s`` (to allow ``tools.runs.*``). Two needles
# to give clearer offender diagnostics.
_NEEDLE_RE_SHELL = re.compile(r'python -m tools\.run( |$)', re.MULTILINE)
_NEEDLE_RE_IMPORT = re.compile(r'^(from|import) tools\.run(\s|$|\.)', re.MULTILINE)

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


def test_no_legacy_python_m_tools_run_invocations():
    """Spec verify form per T-23: ``python -m tools.run`` SHALL NOT appear
    in production code under ``tools/`` or ``training/``. Matches the
    boundary form (followed by space / EOL) the spec lists as the
    canonical verify grep."""
    offenders = []
    for f in _iter_py_files():
        try:
            text = f.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        if _NEEDLE_RE_SHELL.search(text):
            offenders.append(str(f.relative_to(_REPO_ROOT)))
    assert not offenders, (
        f'Found {len(offenders)} file(s) still referencing retired '
        f'``python -m tools.run`` shell invocation (T-23 deleted the '
        f'module per spec L-1 no-shim policy; use '
        f'``python -m tools.runs.train`` instead):\n  ' + '\n  '.join(offenders)
    )


def test_no_legacy_tools_run_imports():
    """Defensive: ``from tools.run`` / ``import tools.run`` SHALL NOT
    appear in production code. The module file is deleted so any such
    import would ImportError, but pinning at lint time catches
    accidental re-introduction in PR review before the failing import
    even runs."""
    offenders = []
    for f in _iter_py_files():
        try:
            text = f.read_text(encoding='utf-8')
        except UnicodeDecodeError:
            continue
        if _NEEDLE_RE_IMPORT.search(text):
            offenders.append(str(f.relative_to(_REPO_ROOT)))
    assert not offenders, (
        f'Found {len(offenders)} file(s) still importing retired '
        f'``tools.run`` module (T-23 deleted the file per spec L-1 '
        f'no-shim policy; the paradigm dispatch body lives in '
        f'``tools.runs._train.dispatch`` and the public entry is '
        f'``tools.runs.train``):\n  ' + '\n  '.join(offenders)
    )
