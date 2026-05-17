"""Regression guard: removed `tools/_archived/<X>.py` MUST have no live imports.

Contract under test
-------------------
After FU-W2.5d batch removal of Dead + Doc-only entries under
``tools/_archived/``, no **executable** repo content (live Python
imports, shell commands, TOML config values) may resolve to a removed
``tools/_archived/<X>.py`` module.

What this test scans
~~~~~~~~~~~~~~~~~~~~
- ``.py`` files — only ``import`` and ``from … import …`` statements
  (Python docstrings / comments / triple-quoted module headers may
  retain historical references for context, per project convention)
- ``.sh`` files — only non-comment lines containing ``python -m
  tools.<name>`` or ``python … tools/<name>.py``
- ``.toml`` files — any reference (TOML doesn't have a runtime
  import vs comment distinction worth respecting; user does NOT
  configure removed paradigms in cfg)

What this test does NOT scan
~~~~~~~~~~~~~~~~~~~~~~~~~~~~
- Markdown prose (``.md``) — documentation may keep historical names
  with explicit ``(historical, archive-removed YYYY-MM)`` annotation
- Python docstrings, comments, triple-quoted strings — these are
  prose-context references, not executable imports

Excluded scan paths (per audit ground rule)
-------------------------------------------
- ``tools/_archived/``              — files being removed; self-refs OK
- ``docs/5_history/``               — historical archive; not active
- ``openspec/changes/archive/``     — archived OpenSpec changes
- ``.git/`` / ``.venv/`` / ``__pycache__/`` / build artifacts

The list of removed names is the **union of all `tools/_archived/<X>`
modules ever removed from the repo**, so this guard catches future
re-introduction of any historically-deleted archived tool. Sources:

- ``decb4a8`` (FU-W4-DMC partial) — `dmc_train`
- ``2e5bc6f`` (FU-W4-PPO) — 6 PPO entries (`ppo_bc_eval_probe`,
  `ppo_calibrate`, `ppo_eval_probe`, `ppo_launch`,
  `ppo_multiseed_aggregate`, `ppo_replay_check`)
- ``ade04ea`` (FU-W2.5d) — 11 entries per
  ``docs/5_history/audits/archived_tools_audit.md`` (Dead + Doc-only
  filtered against the FU-W4-PPO post-state)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Bare names (no extension) of files ever removed from tools/_archived/.
# Union of all historical removals — true regression guard, so future
# re-introduction of any deleted archived tool is caught.
# Keep in sync with new removals; audit doc lives at
# ``docs/5_history/audits/archived_tools_audit.md``.
REMOVED_NAMES: tuple[str, ...] = (
    # ade04ea (FU-W2.5d) Dead
    'cfr_post_gauntlet',
    'cfr_presets',
    'greedy_ladder_stage1',
    'greedy_tiebreak_audit',
    'run_r008_gauntlet',
    # ade04ea (FU-W2.5d) Doc-only
    'eval_bc_ckpt',
    'launch_config',
    'ppo_bc_launch',
    'run_cfr',
    'select_bc_ckpt',
    'test_dice_scheduling',
    # decb4a8 (FU-W4-DMC partial)
    'dmc_train',
    # 2e5bc6f (FU-W4-PPO)
    'ppo_bc_eval_probe',
    'ppo_calibrate',
    'ppo_eval_probe',
    'ppo_launch',
    'ppo_multiseed_aggregate',
    'ppo_replay_check',
)

# Directories whose contents are NOT considered "active" for the purpose
# of this guard.
EXCLUDED_DIR_PARTS: tuple[str, ...] = (
    '.git',
    '.venv',
    '__pycache__',
    'node_modules',
    'artifacts',
    # Historical / archive — by audit ground rule
    'docs/5_history',
    'openspec/changes/archive',
    # The directory being removed itself (now empty / gone, but keep for safety)
    'tools/_archived',
)


def _is_excluded(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    for part in EXCLUDED_DIR_PARTS:
        if rel == part or rel.startswith(part + '/'):
            return True
    return False


def _iter_files(suffix: str) -> list[Path]:
    out: list[Path] = []
    for p in REPO_ROOT.rglob(f'*{suffix}'):
        if not p.is_file():
            continue
        if _is_excluded(p):
            continue
        out.append(p)
    return out


def _py_imports(path: Path, removed: set[str]) -> list[tuple[int, str]]:
    """Return (lineno, snippet) for live Python imports of any removed name."""
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []

    hits: list[tuple[int, str]] = []
    lines = text.splitlines()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _module_hits_removed(alias.name, removed):
                    hits.append((node.lineno, lines[node.lineno - 1].strip()))
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ''
            if _module_hits_removed(mod, removed):
                hits.append((node.lineno, lines[node.lineno - 1].strip()))
            # Also catch `from tools import launch_config` style:
            if mod in ('tools', 'tools._archived'):
                for alias in node.names:
                    if alias.name in removed:
                        hits.append((node.lineno, lines[node.lineno - 1].strip()))
    return hits


def _module_hits_removed(module: str, removed: set[str]) -> bool:
    """True if a Python dotted module path equals or descends into a removed name."""
    if not module:
        return False
    parts = module.split('.')
    # tools.<name> or tools._archived.<name>
    if parts[:1] == ['tools']:
        if len(parts) >= 2 and parts[1] in removed:
            return True
        if len(parts) >= 3 and parts[1] == '_archived' and parts[2] in removed:
            return True
    return False


def _sh_invocations(path: Path, removed: set[str]) -> list[tuple[int, str]]:
    """Return (lineno, line) for non-comment shell lines invoking a removed name."""
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    # `python -m tools.<name>` or `python … tools/<name>.py` (path form)
    name_alt = '|'.join(re.escape(n) for n in removed)
    pattern = re.compile(
        rf'\b(?:python[\w.-]*\s+(?:-m\s+)?tools\.(?:_archived\.)?({name_alt})'
        rf'|tools/(?:_archived/)?({name_alt})\.(?:py|sh))\b'
    )
    for idx, line in enumerate(text.splitlines(), start=1):
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        if pattern.search(line):
            hits.append((idx, line.rstrip()))
    return hits


def _toml_refs(path: Path, removed: set[str]) -> list[tuple[int, str]]:
    """Return (lineno, line) for any reference inside a .toml file."""
    try:
        text = path.read_text(encoding='utf-8')
    except (UnicodeDecodeError, OSError):
        return []
    hits: list[tuple[int, str]] = []
    name_alt = '|'.join(re.escape(n) for n in removed)
    pattern = re.compile(
        rf'\b(?:tools\.(?:_archived\.)?({name_alt})'
        rf'|tools/(?:_archived/)?({name_alt})\.(?:py|sh))\b'
    )
    for idx, line in enumerate(text.splitlines(), start=1):
        # Skip TOML comments (start with #)
        stripped = line.lstrip()
        if stripped.startswith('#'):
            continue
        if pattern.search(line):
            hits.append((idx, line.rstrip()))
    return hits


def test_no_active_imports_of_removed_archived_tools() -> None:
    """Each removed `tools/_archived/<X>.py` must have zero executable refs."""
    removed = set(REMOVED_NAMES)
    all_hits: dict[str, list[tuple[Path, int, str]]] = {}

    for path in _iter_files('.py'):
        for lineno, snippet in _py_imports(path, removed):
            all_hits.setdefault(path.relative_to(REPO_ROOT).as_posix(), []).append((path, lineno, snippet))
    for path in _iter_files('.sh'):
        for lineno, snippet in _sh_invocations(path, removed):
            all_hits.setdefault(path.relative_to(REPO_ROOT).as_posix(), []).append((path, lineno, snippet))
    for path in _iter_files('.toml'):
        for lineno, snippet in _toml_refs(path, removed):
            all_hits.setdefault(path.relative_to(REPO_ROOT).as_posix(), []).append((path, lineno, snippet))

    if all_hits:
        msg_lines = ['Executable references to removed tools/_archived files:']
        for rel, hits in sorted(all_hits.items()):
            msg_lines.append(f'  {rel}:')
            for _, lineno, snippet in hits:
                msg_lines.append(f'    L{lineno}: {snippet}')
        raise AssertionError('\n'.join(msg_lines))
