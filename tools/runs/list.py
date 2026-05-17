"""``tools.runs.list`` — table view of all run metadata records.

Replaces the hand-maintained ``docs/4_runs/registry.md`` per spec T2.
Scans ``artifacts/runs/*.toml`` and emits a fixed-width table sorted
by run_id ascending.

Columns: run_id | paradigm | status | timestamp (date only) |
wall | summary (first sentence).

CLI:

    .venv/bin/python -m tools.runs.list [--root <path>] [--type r|s]

Empty runs dir → prints a friendly hint, exit 0 (not an error — a
fresh repo has nothing to list).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.runs import schema


def _short_ts(ts: str) -> str:
    """Strip iso8601 to date portion (chars before 'T'). Defensive: any
    unexpected shape just returns the original string truncated."""
    if 'T' in ts:
        return ts.split('T', 1)[0]
    return ts[:10]


def _first_sentence(text: str, max_chars: int = 60) -> str:
    """First sentence (split on '. ' / newline), truncated."""
    if not text:
        return ''
    candidate = text.replace('\r', '\n').split('\n', 1)[0]
    if '. ' in candidate:
        candidate = candidate.split('. ', 1)[0]
    if len(candidate) > max_chars:
        candidate = candidate[: max_chars - 1] + '…'
    return candidate


def _collect(root: Path | None, type_filter: str | None) -> list[schema.RunMetadata]:
    """Read every *.toml under runs_dir. Skip files that fail to
    parse (with a stderr warning) — list shouldn't die from one bad
    record, but tell the user."""
    rd = schema.runs_dir(root)
    if not rd.exists():
        return []
    records: list[schema.RunMetadata] = []
    for p in sorted(rd.glob('*.toml')):
        try:
            meta = schema.load_file(p)
        except (ValueError, OSError) as e:
            print(f'tools.runs.list: skipping {p.name}: {e}', file=sys.stderr)
            continue
        # M7 invariant: filename stem must equal internal run_id; otherwise
        # `show <run_id>` opens a different file than `list` reports.
        if p.stem != meta.run_id:
            print(
                f'tools.runs.list: skipping {p.name}: filename stem {p.stem!r} != metadata.run_id {meta.run_id!r}',
                file=sys.stderr,
            )
            continue
        if type_filter is not None and meta.type != type_filter:
            continue
        records.append(meta)
    records.sort(key=lambda m: m.run_id)
    return records


def render_table(records: list[schema.RunMetadata]) -> str:
    """Pure-string render so tests can assert on output without capsys."""
    headers = ('run_id', 'paradigm', 'status', 'date', 'wall', 'summary')
    rows: list[tuple[str, ...]] = []
    for m in records:
        rows.append(
            (
                m.run_id,
                m.paradigm,
                m.status,
                _short_ts(m.timestamp),
                m.summary.wall or '-',
                _first_sentence(m.summary.description),
            )
        )

    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt(row: tuple[str, ...]) -> str:
        return '  '.join(cell.ljust(widths[i]) for i, cell in enumerate(row)).rstrip()

    lines = [fmt(headers), fmt(tuple('-' * w for w in widths))]
    for row in rows:
        lines.append(fmt(row))
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--type', default=None, choices=['r', 's'], dest='type_')
    ap.add_argument('--root', default=None)
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else None
    records = _collect(root, args.type_)
    if not records:
        rd = schema.runs_dir(root)
        print(f'(no runs found under {rd}; register one with `tools.runs.register`)')
        return 0
    sys.stdout.write(render_table(records))
    return 0


if __name__ == '__main__':
    sys.exit(main())
