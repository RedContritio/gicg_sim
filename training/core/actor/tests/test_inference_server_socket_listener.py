"""I29 P1.3b — socket listener integration test。

Mock forward_callback (echo zero logits) + Python TCP client → 验证 listener bind /
accept / per-conn handler / wire decode + encode 全栈 round-trip。

Mac-only Python test;Win box stress 中不连。 后续 P1.5 端到端 Win 实测 fps 时跑真 Go actor
+ 真 InferServer batched_forward。
"""

from __future__ import annotations

import socket
import threading
import time

import numpy as np
import pytest

from training.core.actor.inference_server_socket_listener import (
    start_listener_in_thread,
    stop_listener,
)
from training.core.actor.inference_server_socket_wire import (
    INFER_STATUS_ERR,
    INFER_STATUS_OK,
    InferRequest,
    InferResponse,
    decode_infer_response,
    encode_infer_request,
    read_length_prefixed,
)


def _free_port() -> int:
    """Get an unused localhost port — bind 0 + read assigned。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _echo_logits_callback(req: InferRequest) -> InferResponse:
    """Mock forward:logits = float32([client_id, req_id, n_dyn, n_refs, n_pay])。"""
    return InferResponse(
        status=INFER_STATUS_OK,
        logits=np.array(
            [
                float(req.client_id),
                float(req.req_id),
                float(len(req.dyn_obs)),
                float(len(req.refs)),
                float(len(req.pay)),
            ],
            dtype=np.float32,
        ),
    )


class _SocketIOReader:
    """Adapter:socket.recv → reader.read for read_length_prefixed in client side test。"""

    def __init__(self, conn: socket.socket) -> None:
        self._conn = conn

    def read(self, n: int) -> bytes:
        return self._conn.recv(n)


def test_listener_single_request_round_trip():
    """Single connection,1 req → 1 resp,echo verify。"""
    port = _free_port()
    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, _echo_logits_callback, ready, stop)
    assert ready.wait(timeout=2.0), 'listener ready timeout'
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        req = InferRequest(
            static_hash=b'\xaa' * 16,
            client_id=7,
            req_id=99,
            dyn_obs=np.array([1.0, 2.0, 3.0], dtype=np.float32),
            refs=np.array([10, 20], dtype=np.int64),
            pay=np.array([0.5], dtype=np.float32),
        )
        client.sendall(encode_infer_request(req))
        payload = read_length_prefixed(_SocketIOReader(client))
        resp = decode_infer_response(payload)
        client.close()

        assert resp.status == INFER_STATUS_OK
        # Echo logits = [client_id=7, req_id=99, n_dyn=3, n_refs=2, n_pay=1]
        assert np.array_equal(resp.logits, np.array([7, 99, 3, 2, 1], dtype=np.float32))
    finally:
        stop_listener(stop, thr)


def test_listener_multiple_requests_same_connection():
    """单 connection N 次请求 round-trip,FIFO 顺序。"""
    port = _free_port()
    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, _echo_logits_callback, ready, stop)
    assert ready.wait(timeout=2.0)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        reader = _SocketIOReader(client)
        for i in range(5):
            req = InferRequest(
                static_hash=b'\x00' * 16,
                client_id=i,
                req_id=i * 100,
                dyn_obs=np.array([float(i)], dtype=np.float32),
                refs=np.zeros(0, dtype=np.int64),
                pay=np.zeros(0, dtype=np.float32),
            )
            client.sendall(encode_infer_request(req))
            payload = read_length_prefixed(reader)
            resp = decode_infer_response(payload)
            assert resp.status == INFER_STATUS_OK
            assert int(resp.logits[0]) == i
            assert int(resp.logits[1]) == i * 100
        client.close()
    finally:
        stop_listener(stop, thr)


def test_listener_multiple_concurrent_connections():
    """N=4 并发 connections,各自 1 req,verify 每 conn 独立 thread。"""
    port = _free_port()
    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, _echo_logits_callback, ready, stop)
    assert ready.wait(timeout=2.0)

    results: list[tuple[int, int]] = []
    results_lock = threading.Lock()

    def worker(client_id: int):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.connect(('127.0.0.1', port))
        req = InferRequest(
            static_hash=b'\x00' * 16,
            client_id=client_id,
            req_id=42,
            dyn_obs=np.array([float(client_id)], dtype=np.float32),
            refs=np.zeros(0, dtype=np.int64),
            pay=np.zeros(0, dtype=np.float32),
        )
        sock.sendall(encode_infer_request(req))
        payload = read_length_prefixed(_SocketIOReader(sock))
        resp = decode_infer_response(payload)
        sock.close()
        with results_lock:
            results.append((client_id, int(resp.logits[0])))

    try:
        worker_threads = [threading.Thread(target=worker, args=(cid,)) for cid in range(4)]
        for t in worker_threads:
            t.start()
        for t in worker_threads:
            t.join(timeout=5.0)
        assert len(results) == 4
        for cid, echo_cid in results:
            assert cid == echo_cid
    finally:
        stop_listener(stop, thr)


def test_listener_forward_callback_exception_returns_err():
    """forward_callback 抛异常 → status=ERR response with err_msg,不 kill conn / listener。"""

    def failing_callback(req: InferRequest) -> InferResponse:
        raise RuntimeError(f'intentional fail for client_id={req.client_id}')

    port = _free_port()
    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, failing_callback, ready, stop)
    assert ready.wait(timeout=2.0)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        req = InferRequest(
            static_hash=b'\x00' * 16,
            client_id=5,
            req_id=1,
            dyn_obs=np.zeros(0, dtype=np.float32),
            refs=np.zeros(0, dtype=np.int64),
            pay=np.zeros(0, dtype=np.float32),
        )
        client.sendall(encode_infer_request(req))
        payload = read_length_prefixed(_SocketIOReader(client))
        resp = decode_infer_response(payload)
        client.close()
        assert resp.status == INFER_STATUS_ERR
        assert 'intentional fail' in resp.err_msg
        assert 'client_id=5' in resp.err_msg
    finally:
        stop_listener(stop, thr)


def test_listener_stop_after_idle_period():
    """无 client 时 stop_event set → listener exit < 500 ms。"""
    port = _free_port()
    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, _echo_logits_callback, ready, stop, accept_poll_s=0.05)
    assert ready.wait(timeout=2.0)
    t_start = time.monotonic()
    stop_listener(stop, thr, timeout_s=1.0)
    elapsed = time.monotonic() - t_start
    assert elapsed < 0.5, f'stop took {elapsed:.2f}s, expected < 0.5s'
    assert not thr.is_alive()


def test_listener_bind_fail_sets_ready_anyway():
    """重复 bind 同 port → 第二 listener bind 失败但 ready_event 仍 set(caller 不死等)。"""
    port = _free_port()
    ready1 = threading.Event()
    stop1 = threading.Event()
    thr1 = start_listener_in_thread(port, _echo_logits_callback, ready1, stop1)
    assert ready1.wait(timeout=2.0)

    ready2 = threading.Event()
    stop2 = threading.Event()
    # SO_REUSEADDR 让 macOS bind 不冲突;但 Linux 等可能 still fail。
    # 总之 ready 必须 set(无论 success / fail),caller 不该死等。
    thr2 = start_listener_in_thread(port, _echo_logits_callback, ready2, stop2)
    assert ready2.wait(timeout=2.0), 'second listener ready event never set despite bind outcome'

    stop_listener(stop1, thr1)
    stop_listener(stop2, thr2)
