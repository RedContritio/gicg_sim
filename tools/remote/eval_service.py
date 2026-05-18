"""Standalone evaluation service for AZ / CFR training.

Global singleton — listens on a fixed TCP localhost address (default
``localhost:9100``), accepts matchup requests from any training run.
Each request carries its own player specs, team configuration, and
result output path, so one service instance serves all runs.

The server binds ``localhost`` only (never ``0.0.0.0``) — eval_service
is process-local IPC dressed in TCP for Windows portability, not a
network service. Cross-host topologies (e.g. dispatch from container
to host) wire the loopback port through the container runtime
(``-p 9100:9100``) rather than binding externally.

Start once, leave running across training sessions::

    .venv/bin/python -m tools.remote.eval_service
    .venv/bin/python -m tools.remote.eval_service --host localhost --port 9100 --workers 2

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

# TCP localhost (AF_INET) — Windows-portable (AF_UNIX unavailable on
# Windows). Env-var overrides let container deployments map the
# loopback port through ``-p 9100:9100`` and clients on the same host
# pick up the same default.
DEFAULT_HOST = os.environ.get('GICG_EVAL_HOST', 'localhost')
DEFAULT_PORT = int(os.environ.get('GICG_EVAL_PORT', '9100'))
DEFAULT_METRICS_PATH = '/tmp/gicg_eval_metrics.jsonl'


def _apply_cpu_affinity(spec: str | None) -> None:
    """Parse "0,1,2,3" CSV and pin via psutil.Process().cpu_affinity().

    Silently skips when:
    - spec is None or empty (default: unpinned)
    - psutil missing or psutil.Process has no cpu_affinity (Mac)
    - kernel rejects the requested set (OSError)

    Affinity is a hint, not a contract — same policy as harden_child_env.
    """
    if not spec:
        return
    try:
        cores = [int(s.strip()) for s in spec.split(',') if s.strip()]
    except ValueError as exc:
        raise SystemExit(f'eval_service: --cpu-affinity parse error: {exc} (expected "0,1,2,3" CSV)')
    if not cores:
        return
    try:
        import psutil

        psutil.Process().cpu_affinity(cores)
        print(f'[eval] cpu_affinity pinned to {cores}', flush=True)
    except (ImportError, AttributeError, OSError) as exc:
        # Mac doesn't support cpu_affinity; psutil may also lack it on some
        # platforms. Silent skip — affinity is a hint, not a contract.
        print(f'[eval] cpu_affinity skip ({type(exc).__name__}): {exc}', flush=True)


_SCHEMA_PATH = Path(__file__).parent / 'eval_service_schema.json'
with _SCHEMA_PATH.open('r', encoding='utf-8') as _f:
    REQUEST_SCHEMA = json.load(_f)
# Fail-fast at import: schema itself must be valid JSON Schema 2020-12.
_VALIDATOR = make_validator(REQUEST_SCHEMA)


def build_server(
    host: str,
    port: int,
    max_workers: int = 2,
    metrics_path: str | None = DEFAULT_METRICS_PATH,
) -> EvalServer:
    """Construct an :class:`EvalServer` wired to the module-level
    request schema + validator. Isolated as a helper so tests can
    instantiate a server without duplicating the schema-load
    boilerplate."""
    return EvalServer(
        host=host,
        port=port,
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
        '--host',
        type=str,
        default=DEFAULT_HOST,
        help=f'bind host (default: {DEFAULT_HOST}). Localhost only — external exposure is intentionally not supported.',
    )
    parser.add_argument(
        '--port',
        type=int,
        default=DEFAULT_PORT,
        help=f'bind TCP port (default: {DEFAULT_PORT})',
    )
    parser.add_argument(
        '--workers',
        type=int,
        default=2,
        help='max concurrent evaluations (default: 2)',
    )
    parser.add_argument(
        '--cpu-affinity',
        type=str,
        default=os.environ.get('GICG_EVAL_CPU_AFFINITY'),
        help='comma-separated CPU IDs to pin this eval_service process to '
        '(e.g., "9,10,11,12,13,14,15"). Default: unpinned. '
        'Reads env GICG_EVAL_CPU_AFFINITY when --cpu-affinity not given. '
        'Silently skipped on platforms without psutil.Process.cpu_affinity '
        '(Mac). Match DMCParadigmConfig.cpu_affinity_eval value when '
        'starting eval_service alongside a DMC training run.',
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

    _apply_cpu_affinity(args.cpu_affinity)

    # Warm the DSL parse cache before accepting any gauntlet jobs.
    # This way the service is not vulnerable to the partial-read
    # failure mode — once cache is full, subsequent GameNew calls
    # never touch disk.
    from gicg_env.engine import preload_dsl

    preload_dsl(args.data_dir)
    print(f'[eval] DSL cache warmed from {args.data_dir}', flush=True)

    server = build_server(
        host=args.host,
        port=args.port,
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
