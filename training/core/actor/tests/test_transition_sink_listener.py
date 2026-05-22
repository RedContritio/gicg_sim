"""Transition sink listener integration test。

Python client encode_transition → socket → Python listener decode → sink_callback。
Mac/Linux/Win 同跑(全 Python 端,跨平台 stdlib socket)。

cross-lang(Go encode → Python decode)走 P1.5 端到端 Win 实测时一起跑。
"""

from __future__ import annotations

import socket
import threading
import time

import numpy as np
import pytest

from training.core.actor.transition_sink_listener import (
    start_listener_in_thread,
    stop_listener,
)
from training.core.actor.transition_sink_wire import (
    Transition,
    decode_dmc_payload,
    encode_transition,
)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def test_listener_bind_failure_does_not_set_ready():
    """Bind 失败 → ready_event **不** set(I29 T-RR.6 fail-loud)。

    旧逻辑 bind 失败仍 set ready_event,让 caller(go_collector._bootstrap)误以为
    transition listener 已起 → Go transition push 全连不上而无人知。 用 privileged
    port 1 可靠触发 bind 失败(非 root bind <1024 → PermissionError ⊂ OSError)。"""
    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(1, lambda t: None, ready, stop)
    assert not ready.wait(timeout=1.0), 'bind failed but ready_event was set (caller would false-proceed)'
    stop_listener(stop, thr)


def test_listener_single_transition_roundtrip():
    """单 conn,1 transition push → callback 收到。"""
    port = _free_port()
    received: list[Transition] = []
    lock = threading.Lock()

    def sink(t: Transition) -> None:
        with lock:
            received.append(t)

    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, sink, ready, stop)
    assert ready.wait(timeout=2.0), 'listener ready timeout'
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        t = Transition(client_id=3, episode_id=5, step=7, done=True, payload=b'\xde\xad\xbe\xef')
        client.sendall(encode_transition(t))
        # listener thread 走 callback — wait up to 1s
        deadline = time.time() + 1.0
        while time.time() < deadline:
            with lock:
                if received:
                    break
            time.sleep(0.01)
        client.close()
        with lock:
            assert len(received) == 1
            r = received[0]
        assert r.client_id == 3
        assert r.episode_id == 5
        assert r.step == 7
        assert r.done is True
        assert r.payload == b'\xde\xad\xbe\xef'
    finally:
        stop_listener(stop, thr)


def test_listener_batch_transitions():
    """单 conn 连发 N transition 全收到。"""
    port = _free_port()
    received: list[Transition] = []
    lock = threading.Lock()

    def sink(t: Transition) -> None:
        with lock:
            received.append(t)

    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, sink, ready, stop)
    assert ready.wait(timeout=2.0)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        N = 50
        for i in range(N):
            t = Transition(client_id=1, episode_id=2, step=i, done=(i == N - 1), payload=bytes([i & 0xFF]))
            client.sendall(encode_transition(t))
        # Drain
        deadline = time.time() + 2.0
        while time.time() < deadline:
            with lock:
                if len(received) >= N:
                    break
            time.sleep(0.01)
        client.close()
        with lock:
            assert len(received) == N
            for i, r in enumerate(received):
                assert r.step == i
                assert r.done is (i == N - 1)
    finally:
        stop_listener(stop, thr)


def test_listener_multi_client():
    """N client 同时 push,callback 全收(thread-safe)。"""
    port = _free_port()
    received: list[Transition] = []
    lock = threading.Lock()

    def sink(t: Transition) -> None:
        with lock:
            received.append(t)

    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, sink, ready, stop)
    assert ready.wait(timeout=2.0)
    try:
        N_CLIENTS = 4
        N_PER_CLIENT = 10
        TOTAL = N_CLIENTS * N_PER_CLIENT

        def worker(cid: int) -> None:
            c = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            c.connect(('127.0.0.1', port))
            for i in range(N_PER_CLIENT):
                t = Transition(client_id=cid, episode_id=0, step=i, done=False, payload=b'x')
                c.sendall(encode_transition(t))
            c.close()

        workers = [threading.Thread(target=worker, args=(cid,)) for cid in range(N_CLIENTS)]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

        deadline = time.time() + 3.0
        while time.time() < deadline:
            with lock:
                if len(received) >= TOTAL:
                    break
            time.sleep(0.01)
        with lock:
            assert len(received) == TOTAL, f'expected {TOTAL}, got {len(received)}'
            # Per-client counts
            by_cid = {cid: 0 for cid in range(N_CLIENTS)}
            for r in received:
                by_cid[r.client_id] += 1
            assert all(c == N_PER_CLIENT for c in by_cid.values()), f'uneven: {by_cid}'
    finally:
        stop_listener(stop, thr)


def test_listener_dmc_payload_decode():
    """Push DMC self-contained payload → callback 收到 → decode_dmc_payload 解出。"""
    from training.core.actor.transition_sink_wire import encode_dmc_payload

    port = _free_port()
    received: list[Transition] = []
    lock = threading.Lock()

    def sink(t: Transition) -> None:
        with lock:
            received.append(t)

    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, sink, ready, stop)
    assert ready.wait(timeout=2.0)
    try:
        client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        client.connect(('127.0.0.1', port))
        dyn = np.array([0.1, 0.2, 0.3], dtype=np.float32)
        refs = np.array([0, 1, 2], dtype=np.int64)
        pay = np.array([0.5], dtype=np.float32)
        dmc_payload = encode_dmc_payload(
            chosen_action=4,
            step_in_episode=2,
            reward=0.5,
            n_legal=2,
            static_hash=b'\xde' * 16,
            dyn_obs=dyn,
            refs=refs,
            pay=pay,
        )
        t = Transition(client_id=0, episode_id=1, step=2, done=True, payload=dmc_payload)
        client.sendall(encode_transition(t))
        deadline = time.time() + 1.0
        while time.time() < deadline:
            with lock:
                if received:
                    break
            time.sleep(0.01)
        client.close()
        with lock:
            assert len(received) == 1
            r = received[0]
        dmc = decode_dmc_payload(r.payload, dyn_obs_len=3)
        assert dmc.chosen_action == 4
        assert dmc.step_in_episode == 2
        assert dmc.reward == pytest.approx(0.5)
        assert dmc.n_legal == 2
        np.testing.assert_array_equal(dmc.dyn_obs, dyn)
        np.testing.assert_array_equal(dmc.refs, refs)
        np.testing.assert_array_equal(dmc.pay, pay)
    finally:
        stop_listener(stop, thr)


def test_listener_stop_clean():
    """stop_event set 后 listener 干净退出 < 1s。"""
    port = _free_port()

    def sink(_t):
        pass

    ready = threading.Event()
    stop = threading.Event()
    thr = start_listener_in_thread(port, sink, ready, stop)
    assert ready.wait(timeout=2.0)
    t0 = time.time()
    stop_listener(stop, thr, timeout_s=1.5)
    elapsed = time.time() - t0
    assert elapsed < 1.0, f'stop took {elapsed:.2f}s, expected < 1s'
    assert not thr.is_alive()
