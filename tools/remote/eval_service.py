"""Standalone evaluation service for AZ / CFR training.

Global singleton — listens on a fixed Unix socket (default
``/tmp/gicg_eval.sock``), accepts matchup requests from any
training run. Each request carries its own player specs, team
configuration, and result output path, so one service instance
serves all runs.

Start once, leave running across training sessions::

    .venv/bin/python -m tools.remote.eval_service
    .venv/bin/python -m tools.remote.eval_service --socket /tmp/gicg_eval.sock --workers 2

The authoritative request schema lives in
``tools/remote/eval_service_schema.json`` (JSON Schema 2020-12). The
server validates every incoming request against that schema (plus
runtime checks like ckpt file existence). Clients can query the schema
via ``{"kind": "schema"}``; ``tools/_meta/send_matchup`` uses it to
drive its CLI layout and help text so there's a single source of truth.

Response protocol::

    → <valid request>          ← {"status": "accepted" | "ok" | ...}
    → <invalid request>        ← {"status": "error", "message": "..."}

Kinds: ``gauntlet``, ``status``, ``stop``, ``schema``. See
``eval_service_schema.json`` for field-by-field details.

Module split (kept under 300-line cap):

    eval_service.py         — constants + schema load + CLI main
    eval_service_server.py  — EvalServer (socket / accept loop)
    eval_service_job.py     — ServiceState, validate_request,
                              run_gauntlet_job
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
from pathlib import Path

from tools.remote.eval_service_job import make_validator
from tools.remote.eval_service_server import EvalServer

# ---------------------------------------------------------------------------
# Constants

# GICG_EVAL_SOCKET env var lets the container deployment override the
# socket path (named volume at /var/run/gicg/eval.sock). Falls back to
# /tmp for host-native runs that don't set it.
DEFAULT_SOCKET_PATH = os.environ.get('GICG_EVAL_SOCKET', '/tmp/gicg_eval.sock')
DEFAULT_METRICS_PATH = '/tmp/gicg_eval_metrics.jsonl'

_SCHEMA_PATH = Path(__file__).parent / 'eval_service_schema.json'
with _SCHEMA_PATH.open('r', encoding='utf-8') as _f:
    REQUEST_SCHEMA = json.load(_f)
# Fail-fast at import: schema itself must be valid JSON Schema 2020-12.
_VALIDATOR = make_validator(REQUEST_SCHEMA)


def build_server(
    socket_path: Path,
    max_workers: int = 2,
    metrics_path: str | None = DEFAULT_METRICS_PATH,
) -> EvalServer:
    """Construct an :class:`EvalServer` wired to the module-level
    request schema + validator. Isolated as a helper so tests can
    instantiate a server without duplicating the schema-load
    boilerplate."""
    return EvalServer(
        socket_path=socket_path,
        max_workers=max_workers,
        metrics_path=metrics_path,
        request_schema=REQUEST_SCHEMA,
        validator=_VALIDATOR,
    )


# ---------------------------------------------------------------------------
# CLI


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Global evaluation service for AZ training.',
    )
    parser.add_argument(
        '--socket',
        type=str,
        default=DEFAULT_SOCKET_PATH,
        help=f'socket path (default: {DEFAULT_SOCKET_PATH})',
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=2,
        help='max concurrent evaluations (default: 2)',
    )
    parser.add_argument(
        '--metrics',
        type=str,
        default=DEFAULT_METRICS_PATH,
        help=f'service metrics log path (default: {DEFAULT_METRICS_PATH})',
    )
    parser.add_argument(
        '--data-dir',
        type=str,
        default='data',
        help='DSL data root (default: data). Preloaded into the '
        'parse cache at startup so gauntlet jobs are immune to '
        'mid-run DSL edits.',
    )
    args = parser.parse_args()

    # Warm the DSL parse cache before accepting any gauntlet jobs.
    # This way the service is not vulnerable to the partial-read
    # failure mode — once cache is full, subsequent GameNew calls
    # never touch disk.
    from gicg_env.engine import preload_dsl

    preload_dsl(args.data_dir)
    print(f'[eval] DSL cache warmed from {args.data_dir}', flush=True)

    socket_path = Path(args.socket)

    server = build_server(
        socket_path=socket_path,
        max_workers=args.workers,
        metrics_path=args.metrics,
    )

    def _signal_handler(signum, frame):
        print(f'\n[eval] received signal {signum}, stopping...', flush=True)
        server.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    try:
        server.start()
    finally:
        server.stop()


if __name__ == '__main__':
    main()
