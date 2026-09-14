"""Job execution and service state for tools.eval.eval_service. Split
out to stay under the 300-line size cap. The public entry points
re-exported by tools.eval.eval_service are :class:`ServiceState`,
:func:`validate_request`, and :func:`run_gauntlet_job`."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import jsonschema

_SLOW_JOB_WARN_S = 1800  # 30 min


def make_validator(schema: dict) -> jsonschema.Draft202012Validator:
    """Build a JSON-Schema validator for eval-service requests and
    fail-fast if the schema itself is malformed."""
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def validate_request(req: dict, validator: jsonschema.Draft202012Validator) -> 'str | None':
    """Validate ``req`` against the JSON Schema plus runtime-only
    invariants (file existence). Returns an error message on failure,
    or None if the request is acceptable."""
    errors = list(validator.iter_errors(req))
    if errors:
        # First error is usually the most actionable; include path.
        e = errors[0]
        loc = '/'.join(str(p) for p in e.absolute_path) or '(root)'
        return f'schema: {loc}: {e.message}'
    # Runtime-only checks that JSON Schema can't express:
    if req.get('kind') == 'gauntlet':
        for i, p in enumerate(req.get('players', [])):
            if p.get('type') in ('az', 'cfr'):
                ckpt = p.get('ckpt', '')
                if not Path(ckpt).exists():
                    return f'players[{i}] {p["type"]} ckpt not found: {ckpt!r}'
    return None


class ServiceState:
    """Mutable counters shared across threads (ints are atomic on
    CPython so no lock needed for reads; write_lock guards the
    result file and metrics file)."""

    def __init__(self, metrics_path: str | None = None) -> None:
        self.active: int = 0
        self.completed: int = 0
        self.errors: int = 0
        self.accepted: int = 0
        self.start_t: float = time.perf_counter()
        self.write_lock = threading.Lock()
        self._metrics_path = metrics_path

    def uptime(self) -> float:
        return time.perf_counter() - self.start_t

    def log_metric(self, kind: str, data: dict) -> None:
        """Append one JSONL line to the service metrics log."""
        if self._metrics_path is None:
            return
        entry = {
            'kind': kind,
            't': round(self.uptime(), 3),
            **data,
        }
        with self.write_lock:
            with open(self._metrics_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
                f.flush()


def run_gauntlet_job(req: dict, state: ServiceState) -> None:
    """Execute one matchup request in a worker thread.

    The request must contain ``players`` (list of 2 specs), ``mode``,
    either fixed teams or char_pool+team_size, and ``result_path``."""
    from training.core.matchup.matchup import run_matchup
    from training.core.scenario import decks_arg

    req_id = req.get('id', f'g{req.get("game_marker", 0):05d}')
    game_marker = int(req.get('game_marker', 0))
    result_path = Path(req['result_path'])

    state.active += 1
    t0 = time.perf_counter()
    try:
        result = run_matchup(
            players=req['players'],
            mode=req['mode'],
            team_0=req.get('team_0'),
            team_1=req.get('team_1'),
            char_pool=req.get('char_pool'),
            team_size=req.get('team_size'),
            card_pool=req.get('card_pool'),
            games_per_cell=int(req.get('games_per_cell', 10)),
            max_game_steps=int(req.get('max_game_steps', 400)),
            seed=int(req.get('seed', 0)),
            data_dir=req.get('data_dir'),
            deck_padding=req.get('deck_padding'),
            pool=req.get('pool'),
            decks=decks_arg(req.get('deck_0'), req.get('deck_1')),
            swap_sides=bool(req.get('swap_sides', True)),
        )
        wall_s = time.perf_counter() - t0

        entry = {
            'id': req_id,
            'game_marker': game_marker,
            **result.to_dict(),
        }

        # Append result. Ensure parent dir exists (first request for a
        # new run may arrive before any other file is written there).
        with state.write_lock:
            result_path.parent.mkdir(parents=True, exist_ok=True)
            with open(result_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps(entry) + '\n')
                f.flush()

        agg = result.aggregate
        print(
            f'[eval] done {req_id}: win_rate={agg.win_rate:.3f} '
            f'({agg.wins}/{agg.losses}/{agg.draws} of {agg.n_games}) '
            f'({wall_s:.1f}s)',
            flush=True,
        )
        state.log_metric(
            'job_done',
            {
                'id': req_id,
                'game_marker': game_marker,
                'wall_s': round(wall_s, 1),
                'win_rate': round(agg.win_rate, 4),
                'n_games': agg.n_games,
                'result_path': str(result_path),
            },
        )

        if wall_s > _SLOW_JOB_WARN_S:
            print(
                f'[eval] WARN slow job {req_id}: {wall_s:.0f}s > {_SLOW_JOB_WARN_S}s',
                flush=True,
            )

        state.completed += 1
    except Exception as exc:
        wall_s = time.perf_counter() - t0
        print(
            f'[eval] FAIL {req_id}: {type(exc).__name__}: {exc} ({wall_s:.1f}s)',
            flush=True,
        )
        state.log_metric(
            'job_fail',
            {
                'id': req_id,
                'wall_s': round(wall_s, 1),
                'error': f'{type(exc).__name__}: {exc}',
            },
        )
        state.errors += 1
    finally:
        state.active -= 1
