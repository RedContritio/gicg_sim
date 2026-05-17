"""``tools.runs.show`` — detail dump of a single run metadata record.

Outputs a human-readable key/value listing plus the raw TOML at the
bottom, so this both replaces "open the toml in an editor" and gives
the reader the canonical bytes for sanity check.

CLI:

    .venv/bin/python -m tools.runs.show r013 [--root <path>] [--toml-only]

Exits 1 if the run is not registered.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.runs import schema


def render(meta: schema.RunMetadata, toml_only: bool = False) -> str:
    """Pure-string render for both stdout and tests."""
    if toml_only:
        return schema.dumps(meta)

    lines: list[str] = []
    lines.append(f'run_id       : {meta.run_id}')
    lines.append(f'label        : {meta.label}')
    lines.append(f'type         : {meta.type}')
    lines.append(f'paradigm     : {meta.paradigm}')
    lines.append(f'status       : {meta.status}')
    lines.append(f'timestamp    : {meta.timestamp}')
    lines.append(f'host         : {meta.host}')
    lines.append(f'git_commit   : {meta.git_commit}')
    lines.append(f'cfg_file     : {meta.cfg_file}')
    lines.append(f'cfg_checksum : {meta.cfg_checksum}')
    lines.append(f'cfg_run_label: {meta.cfg_run_label}')
    lines.append(
        f'artifacts_dir: {meta.artifacts_dir or "(unset — run `complete --artifacts-dir <path>` after train)"}'
    )
    lines.append('')
    lines.append(f'[summary] wall={meta.summary.wall or "-"}')
    if meta.summary.description:
        lines.append(f'          description={meta.summary.description}')

    if meta.result.gauntlet is not None:
        g = meta.result.gauntlet
        lines.append('')
        lines.append(f'[result.gauntlet] n={g.n}')
        for k in sorted(g.metrics):
            lines.append(f'  {k}: {g.metrics[k]:.4f}')

    if meta.result.training is not None:
        t = meta.result.training
        lines.append('')
        lines.append(f'[result.training] final_loss={t.final_loss:.4f} n_games_completed={t.n_games_completed}')

    if meta.notes.text:
        lines.append('')
        lines.append(f'[notes] {meta.notes.text}')

    lines.append('')
    lines.append('--- raw toml ---')
    lines.append(schema.dumps(meta).rstrip('\n'))
    return '\n'.join(lines) + '\n'


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('run_id')
    ap.add_argument('--root', default=None)
    ap.add_argument('--toml-only', action='store_true', dest='toml_only')
    args = ap.parse_args(argv)
    root = Path(args.root) if args.root else None
    path = schema.run_path(args.run_id, root=root)
    if not path.exists():
        print(f'tools.runs.show: run {args.run_id} not registered (no file at {path})', file=sys.stderr)
        return 1
    try:
        meta = schema.load_file(path)
    except (ValueError, OSError) as e:
        print(f'tools.runs.show: failed to read {path}: {e}', file=sys.stderr)
        return 1
    sys.stdout.write(render(meta, toml_only=args.toml_only))
    return 0


if __name__ == '__main__':
    sys.exit(main())
