"""Unix-socket server for tools.remote.eval_service. Split out of
eval_service.py to stay under the 300-line size cap. :class:`EvalServer`
owns the accept loop, connection dispatch, and status printer; job
execution and schema validation live in eval_service_job."""

from __future__ import annotations

import json
import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tools.remote.eval_service_job import (
    ServiceState,
    make_validator,
    run_gauntlet_job,
    validate_request,
)

_STATUS_PRINT_INTERVAL_S = 60
_RECV_BUF = 65536

_SCHEMA_PATH = Path(__file__).parent / 'eval_service_schema.json'


def _load_default_schema() -> dict:
    with _SCHEMA_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


class EvalServer:
    """Main server: bind socket, accept connections, dispatch jobs."""

    def __init__(
        self,
        socket_path: Path,
        max_workers: int = 2,
        metrics_path: str | None = None,
        request_schema: dict | None = None,
        validator=None,
    ):
        if request_schema is None:
            request_schema = _load_default_schema()
        if validator is None:
            validator = make_validator(request_schema)
        self.socket_path = socket_path
        self.max_workers = max_workers
        self.state = ServiceState(metrics_path=metrics_path)
        self._stop_event = threading.Event()
        self._executor: ThreadPoolExecutor | None = None
        self._sock: socket.socket | None = None
        self._schema = request_schema
        self._validator = validator

    def start(self) -> None:
        # Clean up stale socket
        if self.socket_path.exists():
            self.socket_path.unlink()

        # Bind
        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.bind(str(self.socket_path))
        self._sock.listen(8)
        self._sock.settimeout(1.0)  # so accept loop checks stop_event

        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

        self._status_thread = threading.Thread(
            target=self._status_loop,
            daemon=True,
        )
        self._status_thread.start()

        print(
            f'[eval] ready: socket={self.socket_path} workers={self.max_workers}',
            flush=True,
        )
        self.state.log_metric(
            'started',
            {
                'socket': str(self.socket_path),
                'workers': self.max_workers,
            },
        )

        self._accept_loop()

    def stop(self) -> None:
        self._stop_event.set()
        if self._executor:
            self._executor.shutdown(wait=True, cancel_futures=False)
        if self._sock:
            self._sock.close()
        if self.socket_path.exists():
            self.socket_path.unlink()
        print('[eval] stopped', flush=True)

    def _accept_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                conn, _ = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break  # socket closed
            try:
                self._handle_connection(conn)
            except Exception as exc:
                print(f'[eval] connection error: {exc}', flush=True)
            finally:
                conn.close()

    def _handle_connection(self, conn: socket.socket) -> None:
        conn.settimeout(5.0)
        data = conn.recv(_RECV_BUF)
        if not data:
            return
        try:
            req = json.loads(data.decode('utf-8').strip())
        except json.JSONDecodeError as exc:
            conn.sendall(json.dumps({'status': 'error', 'message': str(exc)}).encode())
            return

        kind = req.get('kind', '')

        if kind == 'status':
            resp = {
                'status': 'ok',
                'active': self.state.active,
                'completed': self.state.completed,
                'errors': self.state.errors,
                'queued': self.state.accepted - self.state.completed - self.state.errors - self.state.active,
                'uptime_s': round(self.state.uptime(), 1),
            }
            conn.sendall(json.dumps(resp).encode())
            return

        if kind == 'stop':
            conn.sendall(json.dumps({'status': 'stopping'}).encode())
            self._stop_event.set()
            return

        if kind == 'schema':
            conn.sendall(
                json.dumps(
                    {'status': 'ok', 'schema': self._schema},
                    ensure_ascii=False,
                ).encode()
            )
            return

        # Schema validation covers kind in {"gauntlet"} plus all field
        # type / required / choices / conditional-required checks.
        # Unknown kinds fall through the oneOf and produce a schema
        # error here — no separate "unknown kind" branch needed.
        err = validate_request(req, self._validator)
        if err is not None:
            conn.sendall(json.dumps({'status': 'error', 'message': err}).encode())
            return

        if kind == 'gauntlet':
            req_id = req.get('id') or f'g{req.get("game_marker", 0):05d}'
            req['id'] = req_id
            self.state.accepted += 1
            self._executor.submit(run_gauntlet_job, req, self.state)
            conn.sendall(json.dumps({'status': 'accepted', 'id': req_id}).encode())
            return

        # Any kind that passed validation but has no dispatch path.
        conn.sendall(
            json.dumps(
                {
                    'status': 'error',
                    'message': f'kind {kind!r} not dispatchable',
                }
            ).encode()
        )

    def _status_loop(self) -> None:
        while not self._stop_event.wait(_STATUS_PRINT_INTERVAL_S):
            s = self.state
            q = s.accepted - s.completed - s.errors - s.active
            print(
                f'[eval] uptime={s.uptime():.0f}s '
                f'active={s.active} completed={s.completed} '
                f'errors={s.errors} queued={q}',
                flush=True,
            )
            s.log_metric(
                'heartbeat',
                {
                    'active': s.active,
                    'completed': s.completed,
                    'errors': s.errors,
                    'queued': q,
                },
            )
