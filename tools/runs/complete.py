"""``tools.runs.complete`` — finalize a run metadata record.

Loads ``artifacts/runs/<run_id>.toml``, updates ``status`` + optional
``summary.wall`` / ``notes.text`` + optional ``result.gauntlet`` block
from a gauntlet-result JSON.

The gauntlet JSON is expected to have shape::

    {
        "n": 16,
        "results": {"random": 0.875, "mcts_pure_200": 0.5625, ...}
    }

…where ``n`` is the per-opponent sample size and ``results`` is a flat
{opponent_name: win_rate_in_[0,1]} dict. We do not constrain the
opponent names — they vary across paradigm / pool revision.

CLI:

    .venv/bin/python -m tools.runs.complete \\
        --run-id r013 --status done \\
        [--gauntlet-json artifacts/.../gauntlet.json] \\
        [--wall 16.3min] [--notes 'final loss 1.045'] \\
        [--final-loss 1.045] [--n-games 400]

Exits 1 with stderr on:
- run record not found
- gauntlet JSON malformed / missing
- status not in enum
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.runs import schema


def _load_gauntlet_json(path: Path) -> schema.GauntletResult:
    if not path.exists():
        raise FileNotFoundError(f'gauntlet json not found: {path}')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as e:
        raise ValueError(f'gauntlet json {path} is malformed: {e}') from e
    if not isinstance(data, dict):
        raise ValueError(f'gauntlet json {path} must be an object at top level')
    n = data.get('n')
    if n is None:
        raise ValueError(f'gauntlet json {path} missing required "n"')
    results = data.get('results') or {}
    if not isinstance(results, dict):
        raise ValueError(f'gauntlet json {path} "results" must be an object')
    metrics: dict[str, float] = {}
    for k, v in results.items():
        if not isinstance(k, str):
            raise ValueError(f'gauntlet json {path} result key {k!r} must be a string')
        try:
            metrics[k] = float(v)
        except (TypeError, ValueError) as e:
            raise ValueError(f'gauntlet json {path} result {k!r}={v!r} not coercible to float') from e
    return schema.GauntletResult(n=int(n), metrics=metrics)


def complete(
    *,
    run_id: str,
    status: str,
    gauntlet_json: str | None = None,
    wall: str | None = None,
    notes: str | None = None,
    final_loss: float | None = None,
    n_games: int | None = None,
    root: Path | None = None,
) -> schema.RunMetadata:
    """Programmatic entry. Read run toml, mutate, write back."""
    if status not in schema.STATUSES:
        raise ValueError(f'status {status!r} must be one of {sorted(schema.STATUSES)}')

    path = schema.run_path(run_id, root=root)
    if not path.exists():
        raise FileNotFoundError(
            f'run {run_id} not registered (no file at {path}); '
            f'run `tools.runs.register --run-id {run_id} --cfg <path>` first'
        )
    meta = schema.load_file(path)
    meta.status = status

    if wall is not None:
        meta.summary.wall = wall
    if notes is not None:
        meta.notes.text = notes

    if gauntlet_json is not None:
        meta.result.gauntlet = _load_gauntlet_json(Path(gauntlet_json))

    # Training block: populate iff either field passed; coexist with gauntlet.
    if final_loss is not None or n_games is not None:
        existing = meta.result.training or schema.TrainingResult()
        if final_loss is not None:
            existing.final_loss = float(final_loss)
        if n_games is not None:
            existing.n_games_completed = int(n_games)
        meta.result.training = existing

    schema.save_file(meta, path)
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--run-id', required=True)
    ap.add_argument('--status', required=True, choices=sorted(schema.STATUSES))
    ap.add_argument('--gauntlet-json', default=None)
    ap.add_argument('--wall', default=None, help="e.g. '16.3min'")
    ap.add_argument('--notes', default=None)
    ap.add_argument('--final-loss', default=None, type=float)
    ap.add_argument('--n-games', default=None, type=int, dest='n_games')
    ap.add_argument('--root', default=None, help='override repo root (testing only)')
    args = ap.parse_args(argv)
    try:
        meta = complete(
            run_id=args.run_id,
            status=args.status,
            gauntlet_json=args.gauntlet_json,
            wall=args.wall,
            notes=args.notes,
            final_loss=args.final_loss,
            n_games=args.n_games,
            root=Path(args.root) if args.root else None,
        )
    except (ValueError, FileNotFoundError) as e:
        print(f'tools.runs.complete: {e}', file=sys.stderr)
        return 1
    print(f'{meta.run_id} {meta.status}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
