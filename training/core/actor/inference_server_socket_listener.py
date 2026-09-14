"""Socket listener for the Go actor ↔ Python inference protocol.

The listener binds loopback TCP, accepts each connection in a daemon
thread, decodes length-prefixed requests, calls a supplied synchronous
callback, and encodes the response. The production callback places socket
requests onto the inference server's shared batch queue.

The accept loop polls ``stop_event``. A handler blocked on an idle connection
exits only when the peer closes or the process ends, so handler threads are
daemons.
"""

from __future__ import annotations

import socket
import sys
import threading
from typing import Callable, Optional

from training.core.actor.inference_server_socket_wire import (
    InferRequest,
    InferResponse,
    decode_infer_request,
    encode_infer_response,
    read_length_prefixed,
)


class _SocketReader:
    """Adapt ``socket.recv(n)`` to the reader interface used by the wire parser."""

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn

    def read(self, n: int) -> bytes:
        return self._conn.recv(n)


# Type alias for the request callback.
ForwardCallback = Callable[[InferRequest], InferResponse]


def start_listener_in_thread(
    port: int,
    forward_callback: ForwardCallback,
    ready_event: threading.Event,
    stop_event: threading.Event,
    *,
    host: str = '127.0.0.1',
    accept_poll_s: float = 0.1,
) -> threading.Thread:
    """Start the accept loop and signal readiness after binding.

    ``forward_callback`` may run concurrently in multiple connection
    threads, so stateful implementations must synchronize their state. The
    returned daemon thread can be joined after setting ``stop_event``.
    """
    thr = threading.Thread(
        target=_listener_loop,
        args=(port, host, forward_callback, ready_event, stop_event, accept_poll_s),
        daemon=True,
        name=f'InfServerSocketListener-{port}',
    )
    thr.start()
    return thr


def _listener_loop(
    port: int,
    host: str,
    forward_callback: ForwardCallback,
    ready_event: threading.Event,
    stop_event: threading.Event,
    accept_poll_s: float,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        # Do not set readiness after a bind failure; the parent then times out.
        print(f'[InfServerSocketListener] bind {host}:{port} failed: {exc}', file=sys.stderr, flush=True)
        return
    sock.listen(128)  # backlog 128 — N=16 actor 充足
    sock.settimeout(accept_poll_s)
    ready_event.set()
    handler_threads: list[threading.Thread] = []
    try:
        while not stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except (OSError, socket.timeout):
                # Periodic timeout or socket closure; re-check stop_event.
                continue
            # Handlers block until the peer sends data or closes. They are
            # daemons and may outlive the listener thread during shutdown.
            conn.settimeout(None)
            thr = threading.Thread(
                target=_per_conn_handler,
                args=(conn, forward_callback, stop_event),
                daemon=True,
                name='InfServerSocketHandler',
            )
            thr.start()
            handler_threads.append(thr)
            # Reap completed connection threads.
            handler_threads[:] = [t for t in handler_threads if t.is_alive()]
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _per_conn_handler(
    conn: socket.socket,
    forward_callback: ForwardCallback,
    stop_event: threading.Event,
) -> None:
    """Decode, forward, and reply until EOF, shutdown, or an I/O error."""
    reader = _SocketReader(conn)
    try:
        while not stop_event.is_set():
            try:
                payload = read_length_prefixed(reader)
            except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
                return
            try:
                req = decode_infer_request(payload)
                resp = forward_callback(req)
            except Exception as exc:  # noqa: BLE001 — forward 失败不该 kill conn
                # Report the failure locally and return it to the actor.
                print(
                    f'[InfServerSocketListener] forward error: {type(exc).__name__}: {exc}',
                    file=sys.stderr,
                    flush=True,
                )
                resp = InferResponse(status=1, err_msg=f'{type(exc).__name__}: {exc}')
            try:
                conn.sendall(encode_infer_response(resp))
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
    finally:
        try:
            conn.close()
        except OSError:
            pass


def stop_listener(
    stop_event: threading.Event, listener_thread: Optional[threading.Thread], timeout_s: float = 2.0
) -> None:
    """Set the stop event and join the listener up to ``timeout_s``."""
    stop_event.set()
    if listener_thread is not None and listener_thread.is_alive():
        listener_thread.join(timeout=timeout_s)
