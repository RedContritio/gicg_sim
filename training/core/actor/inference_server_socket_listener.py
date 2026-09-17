"""Socket listener for the Go actor ↔ Python inference protocol.

The listener binds loopback TCP, accepts each connection in a daemon
thread, decodes length-prefixed requests, calls a supplied synchronous
callback, and encodes the response. The production callback places socket
requests onto the inference server's shared batch queue.

The accept loop polls ``stop_event``. Connection reads also poll so idle
handlers observe shutdown instead of waiting indefinitely for their peer.
"""

from __future__ import annotations

import socket
import sys
import threading
import time
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

    def __init__(
        self,
        conn: socket.socket,
        stop_event: threading.Event,
        poll_s: float,
    ) -> None:
        self._conn = conn
        self._stop_event = stop_event
        self._poll_s = poll_s

    def read(self, n: int) -> bytes:
        while True:
            try:
                return self._conn.recv(n)
            except socket.timeout:
                if self._stop_event.is_set():
                    raise EOFError('listener stopping') from None


# Type alias for the request callback.
ForwardCallback = Callable[[InferRequest], InferResponse]


class _ListenerState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._listener_sock: Optional[socket.socket] = None
        self._connections: set[socket.socket] = set()
        self._handler_threads: list[threading.Thread] = []
        self._closed = False

    def set_listener_socket(self, sock: socket.socket) -> None:
        with self._lock:
            self._listener_sock = sock

    def add_handler(self, conn: socket.socket, thr: threading.Thread) -> None:
        close_conn = False
        with self._lock:
            self._handler_threads.append(thr)
            if self._closed:
                close_conn = True
            else:
                self._connections.add(conn)
        if close_conn:
            _close_socket(conn)

    def remove_handler(self, conn: socket.socket, thr: threading.Thread) -> None:
        with self._lock:
            self._connections.discard(conn)
            try:
                self._handler_threads.remove(thr)
            except ValueError:
                pass

    def close(self) -> list[threading.Thread]:
        with self._lock:
            self._closed = True
            listener_sock = self._listener_sock
            connections = list(self._connections)
            handler_threads = list(self._handler_threads)
        if listener_sock is not None:
            _close_socket(listener_sock)
        for conn in connections:
            _close_socket(conn)
        return handler_threads


def _close_socket(sock: socket.socket) -> None:
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def start_listener_in_thread(
    port: int,
    forward_callback: ForwardCallback,
    ready_event: threading.Event,
    stop_event: threading.Event,
    *,
    host: str = '127.0.0.1',
    accept_poll_s: float = 0.1,
    read_poll_s: float = 0.1,
) -> threading.Thread:
    """Start the accept loop and signal readiness after binding.

    ``forward_callback`` may run concurrently in multiple connection
    threads, so stateful implementations must synchronize their state. The
    returned daemon thread can be joined after setting ``stop_event``.
    """
    state = _ListenerState()
    thr = threading.Thread(
        target=_listener_loop,
        args=(
            state,
            port,
            host,
            forward_callback,
            ready_event,
            stop_event,
            accept_poll_s,
            read_poll_s,
        ),
        daemon=True,
        name=f'InfServerSocketListener-{port}',
    )
    setattr(thr, '_gicg_listener_state', state)
    thr.start()
    return thr


def _listener_loop(
    state: _ListenerState,
    port: int,
    host: str,
    forward_callback: ForwardCallback,
    ready_event: threading.Event,
    stop_event: threading.Event,
    accept_poll_s: float,
    read_poll_s: float,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    state.set_listener_socket(sock)
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
    try:
        while not stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except (OSError, socket.timeout):
                # Periodic timeout or socket closure; re-check stop_event.
                continue
            conn.settimeout(read_poll_s)
            thr = threading.Thread(
                target=_per_conn_handler,
                args=(conn, state, forward_callback, stop_event, read_poll_s),
                daemon=True,
                name='InfServerSocketHandler',
            )
            thr.start()
            state.add_handler(conn, thr)
    finally:
        _close_socket(sock)


def _per_conn_handler(
    conn: socket.socket,
    state: _ListenerState,
    forward_callback: ForwardCallback,
    stop_event: threading.Event,
    read_poll_s: float,
) -> None:
    """Decode, forward, and reply until EOF, shutdown, or an I/O error."""
    reader = _SocketReader(conn, stop_event, read_poll_s)
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
        state.remove_handler(conn, threading.current_thread())
        _close_socket(conn)


def stop_listener(
    stop_event: threading.Event, listener_thread: Optional[threading.Thread], timeout_s: float = 2.0
) -> None:
    """Stop accepting, close active connections, and join within ``timeout_s``."""
    stop_event.set()
    if listener_thread is None:
        return
    state = getattr(listener_thread, '_gicg_listener_state', None)
    deadline = time.monotonic() + timeout_s
    handler_threads: list[threading.Thread] = []
    if state is not None:
        handler_threads.extend(state.close())
    if listener_thread.is_alive():
        listener_thread.join(timeout=max(0.0, deadline - time.monotonic()))
    if state is not None:
        handler_threads.extend(state.close())
    for thr in handler_threads:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        thr.join(timeout=remaining)
