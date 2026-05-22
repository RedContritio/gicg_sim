"""Socket listener for Go actor → Python transition sink protocol。

Mirror inference_server_socket_listener.py 结构,但本 listener 走 transition push 方向
(read-only — Python 不回写,Go 单向 push)。

设计:
- ``start_listener_in_thread(port, sink_callback, ready_event, stop_event)``:bind localhost TCP +
  accept loop + per-conn handler thread。 sink_callback 接 ``Transition`` envelope(decoded)
  — caller-supplied function 把 Transition 喂到自己的 collector buffer / queue / SHMRing。
- Per-conn handler 跑独立 threading.Thread + read length-prefix → decode → sink_callback。
  conn EOF / IO err 静默退出。 stop_event set 时通过 socket.settimeout polling 退出 < 100 ms。

Limitation(P1.4 minimum):
- sink_callback 在 per-conn handler thread 调,N actor → N thread。 sink 实现要自 thread-safe
  (Python GIL 让 simple list.append OK,但 stateful collector / sized queue 需 lock)。
- 无 backpressure — Go push 速度 > Python consume → callback 内 stage 满则 callback 自身阻塞
  (Go side 看见 socket write 阻塞)。 P3 perf 数据驱动 SHM 优化时改 ring。
"""

from __future__ import annotations

import socket
import sys
import threading
from typing import Callable, Optional

from training.core.actor.transition_sink_wire import (
    Transition,
    decode_transition,
    read_length_prefixed,
)


class _SocketReader:
    """Adapt socket.recv to reader.read(n) interface for read_length_prefixed。"""

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn

    def read(self, n: int) -> bytes:
        return self._conn.recv(n)


SinkCallback = Callable[[Transition], None]


def start_listener_in_thread(
    port: int,
    sink_callback: SinkCallback,
    ready_event: threading.Event,
    stop_event: threading.Event,
    *,
    host: str = '127.0.0.1',
    accept_poll_s: float = 0.1,
) -> threading.Thread:
    """Spawn accept loop in daemon thread。 ``ready_event`` set 后 caller 可以 connect。
    ``stop_event`` set → accept loop break + sock close。 returns the thread for join。
    """
    thr = threading.Thread(
        target=_listener_loop,
        args=(port, host, sink_callback, ready_event, stop_event, accept_poll_s),
        daemon=True,
        name=f'TransitionSinkListener-{port}',
    )
    thr.start()
    return thr


def _listener_loop(
    port: int,
    host: str,
    sink_callback: SinkCallback,
    ready_event: threading.Event,
    stop_event: threading.Event,
    accept_poll_s: float,
) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind((host, port))
    except OSError as exc:
        # Bind 失败 → fail-loud:打印 stderr + **不** set ready_event。 旧逻辑 set 之
        # 让 caller 误以为 listener 已起(实际无),后续 Go transition push 全连不上而
        # 无人知。 不 set → caller 的 ready.wait() 超时 → caller raise(I29 T-RR.6)。
        print(f'[TransitionSinkListener] bind {host}:{port} failed: {exc}', file=sys.stderr, flush=True)
        return
    sock.listen(128)
    sock.settimeout(accept_poll_s)
    ready_event.set()
    handler_threads: list[threading.Thread] = []
    try:
        while not stop_event.is_set():
            try:
                conn, _addr = sock.accept()
            except (OSError, socket.timeout):
                continue
            conn.settimeout(None)
            thr = threading.Thread(
                target=_per_conn_handler,
                args=(conn, sink_callback, stop_event),
                daemon=True,
                name='TransitionSinkHandler',
            )
            thr.start()
            handler_threads.append(thr)
            handler_threads[:] = [t for t in handler_threads if t.is_alive()]
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _per_conn_handler(
    conn: socket.socket,
    sink_callback: SinkCallback,
    stop_event: threading.Event,
) -> None:
    """Per-conn loop:read Transition envelope → decode → sink_callback,直到 conn EOF 或
    stop_event。 sink_callback exception → log + 关 conn(不 kill 整 listener)。"""
    reader = _SocketReader(conn)
    try:
        while not stop_event.is_set():
            try:
                payload = read_length_prefixed(reader)
            except (EOFError, ConnectionResetError, BrokenPipeError, OSError):
                return
            try:
                t = decode_transition(payload)
                sink_callback(t)
            except Exception as exc:  # noqa: BLE001 — sink 失败不该 kill conn
                print(
                    f'[TransitionSink] decode/sink error: {type(exc).__name__}: {exc}',
                    file=sys.stderr,
                    flush=True,
                )
                # decode 失败往 conn 后续也很可能错,close conn 让 Go side 重连
                return
    finally:
        try:
            conn.close()
        except OSError:
            pass


def stop_listener(
    stop_event: threading.Event, listener_thread: Optional[threading.Thread], timeout_s: float = 2.0
) -> None:
    """Set stop_event + join listener thread。 join 超时即放弃(daemon=True fallback kill)。"""
    stop_event.set()
    if listener_thread is not None and listener_thread.is_alive():
        listener_thread.join(timeout=timeout_s)
