"""DEPRECATED: Auto-append a row to `docs/4_runs/registry.md`.

⚠ DEPRECATED (core-network-generic-promotion Phase 5, 2026-05-17;
re-affirmed by tools/runs clean-slate redesign 2026-05-18):
this tool drove the legacy ``docs/4_runs/registry.md`` markdown
workflow. Phase 0 of ``core-network-generic-promotion`` archived
``docs/4_runs/registry.md`` to
``docs/5_history/runs_pre_redesign_2026_05_17.md`` and replaced this
tool with the new ``tools/runs/`` CLI suite (post-redesign: ``train`` /
``mark`` / ``recover`` / ``list`` / ``show`` / ``sync``). New code
SHALL use ``tools.runs.train`` etc., not this module. Kept for orphan
callers and historical reference; subject to git-rm in a future
cleanup change.

Eliminates the "forgot to register before launching" drift: the
launcher(`tools.run` paradigm dispatch)calls this at startup and the
row lands with `status=pending`. On completion the launcher (or the
human) flips status + fills the result cell; the ID is the return
value.

CLI:
    .venv/bin/python -m tools.register_run --type r \\
        --label r009_foo --config 'slow 1500g, team_size=2' \\
        [--status pending] [--started 2026-04-24]

Returns: the allocated id (e.g. `r009`) on stdout; nonzero exit if
the table section is missing or the label collides.
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path
from typing import Optional

REGISTRY_PATH = Path('docs/4_runs/registry.md')

# Map --type flag to the markdown section header its table lives under.
SECTION_HEADERS = {
    's': '### Bench / smoke (`s`)',
    'r': '### Runs (`r`)',
}


def _split_sections(text: str) -> list[tuple[str, int, int]]:
    """Return (header_line, start_idx, end_idx) for each H3-delimited
    section; end_idx is exclusive and bounded by the next H3 or EOF."""
    lines = text.splitlines(keepends=True)
    headers = [i for i, ln in enumerate(lines) if ln.startswith('### ')]
    sections = []
    for k, i in enumerate(headers):
        end = headers[k + 1] if k + 1 < len(headers) else len(lines)
        sections.append((lines[i].rstrip('\n'), i, end))
    return sections


def _locate_table(lines: list[str], start: int, end: int) -> tuple[int, int]:
    """Within lines[start:end], find the bounds of the markdown table
    (first line starting with '|' through last consecutive '|' line).

    Returns (tbl_start, tbl_end_exclusive). Raises if no table."""
    i = start
    while i < end and not lines[i].startswith('|'):
        i += 1
    if i >= end:
        raise RuntimeError('no markdown table in section')
    tbl_start = i
    while i < end and lines[i].startswith('|'):
        i += 1
    return tbl_start, i


def _next_nnn(lines: list[str], tbl_start: int, tbl_end: int, type_prefix: str) -> int:
    """Scan table rows (skipping the 2 header rows) for existing IDs
    starting with type_prefix; return max+1 or 1."""
    pat = re.compile(rf'\|\s*{type_prefix}(\d+)')
    max_n = 0
    for ln in lines[tbl_start + 2 : tbl_end]:
        m = pat.match(ln)
        if m:
            max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def _row_exists(lines: list[str], tbl_start: int, tbl_end: int, label: str) -> bool:
    for ln in lines[tbl_start + 2 : tbl_end]:
        if f'| {label} ' in ln or f'|{label}|' in ln:
            return True
    return False


def register(
    type_prefix: str,
    label: str,
    config: str,
    status: str = 'pending',
    started: Optional[str] = None,
    registry_path: Path = REGISTRY_PATH,
) -> str:
    """Allocate next id, insert row, return id string (e.g. 'r009').

    Idempotent-ish: if an existing row already matches `label`, raise
    rather than duplicating — callers should check before re-launching.
    """
    if type_prefix not in SECTION_HEADERS:
        raise ValueError(f'type_prefix must be one of {list(SECTION_HEADERS)}, got {type_prefix!r}')
    text = registry_path.read_text(encoding='utf-8')
    lines = text.splitlines(keepends=True)

    target_header = SECTION_HEADERS[type_prefix]
    section = next((s for s in _split_sections(text) if s[0] == target_header), None)
    if section is None:
        raise RuntimeError(f'registry section not found: {target_header}')
    _, sec_start, sec_end = section
    # Scan the WHOLE section (not just first table block) — sections can
    # have multiple table blocks separated by blockquotes / prose, so
    # `_locate_table`'s "first contiguous |-block" view would miss later
    # rows (e.g., the `s` section has retrospective blockquotes between
    # s007 and s008+).
    section_rows = [ln for ln in lines[sec_start:sec_end] if ln.startswith('|')]
    if _row_exists(section_rows, 0, len(section_rows), label):
        raise RuntimeError(f'label already registered: {label}')
    next_nnn = _next_nnn(section_rows, 0, len(section_rows), type_prefix)
    # Convention: label = <type><NNN>_<slug>. NNN must be either the next
    # free slot (new run) or an already-claimed slot (multi-seed: same NNN,
    # different label suffix `_seedN`). This keeps multi-seed runs grouped
    # under one NNN rather than skipping versions.
    label_match = re.match(rf'^{type_prefix}(\d+)_', label)
    if label_match is None:
        raise RuntimeError(f'label {label!r} does not match <type><NNN>_<slug> convention')
    label_nnn = int(label_match.group(1))
    existing_nnns = {int(m.group(1)) for m in (re.match(rf'\|\s*{type_prefix}(\d+)', ln) for ln in section_rows) if m}
    # Insertion point: right after the last `|` line in section (keep
    # contiguous with existing rows; trailing blockquotes stay below).
    last_row_lineno = sec_start - 1
    for i in range(sec_start, sec_end):
        if lines[i].startswith('|'):
            last_row_lineno = i
    insert_at = last_row_lineno + 1
    if label_nnn in existing_nnns:
        # Sub-row under existing slot (multi-seed). Re-use the NNN; do not advance.
        rid = f'{type_prefix}{label_nnn:03d}'
    elif label_nnn == next_nnn:
        # New slot claim.
        rid = f'{type_prefix}{next_nnn:03d}'
    else:
        raise RuntimeError(
            f'label NNN mismatch: label={label} embeds {label_match.group(1)} '
            f'but next free is {next_nnn:03d} and no existing slot matches. '
            f'Either rename label/file to {type_prefix}{next_nnn:03d}_<slug>, '
            f'or first register an anchor row at the gap.'
        )
    started = started or datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
    new_row = f'| {rid} | {label} | {started} | {config} | **{status}** | — |\n'
    lines.insert(insert_at, new_row)
    registry_path.write_text(''.join(lines), encoding='utf-8')
    return rid


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--type', required=True, choices=list(SECTION_HEADERS))
    ap.add_argument('--label', required=True)
    ap.add_argument('--config', required=True)
    ap.add_argument('--status', default='pending')
    ap.add_argument('--started', default=None)
    ap.add_argument('--registry', default=str(REGISTRY_PATH))
    args = ap.parse_args()
    try:
        rid = register(
            args.type,
            args.label,
            args.config,
            status=args.status,
            started=args.started,
            registry_path=Path(args.registry),
        )
    except Exception as e:
        print(f'register_run: {e}', file=sys.stderr)
        return 1
    print(rid)
    return 0


if __name__ == '__main__':
    sys.exit(main())
