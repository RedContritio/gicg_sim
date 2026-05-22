"""Socket listener for Go actor ↔ Python InferenceServer protocol。

P1.3b minimum:listener 独立 function(可在 InferenceServer 子进程内 spawn,or unit-test
直接调)。 P1.3c 集成到 InferenceServer.spawn lifecycle + 用 server batched_forward 而非
caller-supplied callback。

设计:
- ``start_listener_in_thread(port, forward_callback, ready_event, stop_event)``:
  bind localhost TCP + accept loop + per-conn handler thread。 forward_callback 接
  ``InferRequest`` 返 ``InferResponse``,实现 paradigm-specific decode + network forward。
- Per-conn handler 跑独立 threading.Thread + read length-prefix → decode → forward_callback
  → encode → write back socket。 conn 关闭 / EOFError / 其它 IO err 安静退出。
- stop_event set 时 accept loop 通过 socket.settimeout 0.1s polling 退出,< 100 ms 反应。

Limitation(P1.3b minimum):
- forward_callback 是 per-request synchronous(no batching across socket clients)。 P1.3c
  优化 — listener push 到 server.request_queue + per-conn response_q routing,跟 mp.Queue
  path 合 batching。
- 每 conn 独立 thread。 N actor → N conn → N thread。 Python GIL 让 thread 之间 forward
  serialized,这个 trade-off OK for P1.3b mock(GPU forward 通常 dominant)。
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
    """Adapt ``socket.recv(n)`` to ``reader.read(n)`` interface for read_length_prefixed。

    ``socket.recv`` may return < n bytes(short read);_read_exact in wire module loops
    until full n collected。 reader.read 同 file.read semantics — 短返表示 EOF。 这里
    recv 返 0 → 我们返 b'' 让 _read_exact raise EOFError。
    """

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn

    def read(self, n: int) -> bytes:
        return self._conn.recv(n)


# Type alias for paradigm-specific forward callback。
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
    """Spawn accept loop in daemon thread。 ``ready_event`` set 后 caller 可以 connect。
    ``stop_event`` set → accept loop break + sock close。 returns the thread for join。

    forward_callback 在 **per-conn handler thread** 内调用,可能并发(N conn → N thread
    同时 call)。 callback 实现需自己 sync(Python GIL 让简单 forward_one 已 thread-safe,
    但 stateful caches 需 lock)。

    Listener thread 跟 per-conn handler threads 都 daemon=True — process exit 时强制 kill。
    Caller 应在 normal shutdown 时 set stop_event 后 join listener,daemon=True 仅 fallback。
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
        # Bind 失败 → fail-loud:打印 stderr + **不** set ready_event。 旧逻辑 set 之
        # 让 caller(InfServer _server_loop)误以为 listener 已起 → Go inference 全
        # 连不上而无人知。 不 set → caller 的 ready.wait() 超时 → raise(I29 T-RR.6)。
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
                # Periodic timeout — re-check stop_event。 ConnectionAbortedError 同
                # poll branch(防 graceful shutdown 时崩)。
                continue
            conn.settimeout(None)  # blocking IO in handler;handler 自身 select-able via stop_event 配 read 短超时
            thr = threading.Thread(
                target=_per_conn_handler,
                args=(conn, forward_callback, stop_event),
                daemon=True,
                name='InfServerSocketHandler',
            )
            thr.start()
            handler_threads.append(thr)
            # Cleanup dead threads(reap N=actor scale list)— 每次 accept 后 quick filter
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
    """Per-conn loop:read InferRequest → forward → write InferResponse,直到 conn EOF 或
    stop_event。 IO errors → quiet close conn。 forward_callback exception → write status=ERR
    response with str(exc),不 kill 整 listener。"""
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
                # fail-loud:打印 stderr —— forward 异常(如 wire/max_actions 配置错)
                # 经 ERR response 回 actor 致其退出,但 InfServer 端也须留日志,否则
                # systematic bug 排查时 InfServer 侧一无所获(I29 T-RR.6 review)。
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
    """Set stop_event + join listener thread。 join 超时即放弃(daemon=True fallback kill)。"""
    stop_event.set()
    if listener_thread is not None and listener_thread.is_alive():
        listener_thread.join(timeout=timeout_s)
