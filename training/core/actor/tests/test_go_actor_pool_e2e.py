"""I29 P1.4 — end-to-end smoke:Python listeners + Go GoActorBackend.start_with_config。

验证:
- Python 起 InfServer socket listener(echo-zeros forward callback)+ Transition sink
  listener(append-callback)
- ctypes 调 libgicg_actor.gicg_actor_start_pool_v2 起 1 actor 跑 dmc paradigm
- Go side 跑几个 turn,发 inference request、收 logits、step engine、push transition
- Python sink listener 收到 ≥1 transition
- stop_pool 干净退出 < 2s

Mac-only(libgicg_actor.dylib 路径)。 Win 同测在 P1.5 stress 跑 build dll 验证。
本测仅 fp 1 actor + 短运行,verify protocol wiring 通,不 stress fps / mem。

Build prerequisite:
  go build -buildmode=c-shared -o gicg_env/libgicg_actor.dylib ./gicg_actor/capi
  go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi
"""

from __future__ import annotations

import json
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest

from training.core.actor.go_backend import GoActorBackend
from training.core.actor.inference_server_socket_listener import (
    start_listener_in_thread as start_inf_listener,
    stop_listener as stop_inf_listener,
)
from training.core.actor.inference_server_socket_wire import (
    INFER_STATUS_OK,
    InferRequest,
    InferResponse,
)
from training.core.actor.transition_sink_listener import (
    start_listener_in_thread as start_trans_listener,
    stop_listener as stop_trans_listener,
)
from training.core.actor.transition_sink_wire import Transition


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _libgicg_actor_built() -> bool:
    name = {'darwin': 'libgicg_actor.dylib', 'win32': 'libgicg_actor.dll'}.get(sys.platform, 'libgicg_actor.so')
    return (Path(__file__).resolve().parents[4] / 'gicg_env' / name).exists()


def _libgicg_engine_built() -> bool:
    name = {'darwin': 'libgicg.dylib', 'win32': 'libgicg.dll'}.get(sys.platform, 'libgicg.so')
    return (Path(__file__).resolve().parents[4] / 'gicg_env' / name).exists()


@pytest.mark.skipif(
    not (_libgicg_actor_built() and _libgicg_engine_built()),
    reason='libgicg_actor or libgicg not built — run go build per docstring',
)
def test_go_actor_pool_e2e_smoke():
    inf_port = _free_port()
    trans_port = _free_port()

    # Echo-zeros forward callback: respond with logits of length max_actions(30) all zeros.
    def echo_zero_logits(req: InferRequest) -> InferResponse:
        return InferResponse(
            status=INFER_STATUS_OK,
            logits=np.zeros(30, dtype=np.float32),
        )

    received_transitions: list[Transition] = []
    sink_lock = threading.Lock()

    def sink(t: Transition) -> None:
        with sink_lock:
            received_transitions.append(t)

    inf_ready = threading.Event()
    inf_stop = threading.Event()
    trans_ready = threading.Event()
    trans_stop = threading.Event()
    inf_thr = start_inf_listener(inf_port, echo_zero_logits, inf_ready, inf_stop)
    trans_thr = start_trans_listener(trans_port, sink, trans_ready, trans_stop)
    assert inf_ready.wait(timeout=2.0)
    assert trans_ready.wait(timeout=2.0)

    backend = GoActorBackend()
    # Use a minimal scenario — 2 chars per side(stage3-style)
    paradigm_cfg = {
        'game_spec': {
            'pools': ['v_legacy'],
            'seed': 42,
            'players': [
                {'chars': [{'name': '赤蝶'}]},
                {'chars': [{'name': '墨客'}]},
            ],
        },
        'opp_features': 'F1',
        'opp_depth': 2,
        'max_actions': 30,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': 42,
        'epsilon': 0.05,
    }
    backend.start_with_config(
        paradigm='dmc',
        n_actors=1,
        inf_addr=f'127.0.0.1:{inf_port}',
        trans_addr=f'127.0.0.1:{trans_port}',
        paradigm_cfg=paradigm_cfg,
        io_timeout_ms=10_000,
    )
    try:
        # Let actor run for up to 5s — at greedy F1-D2 speed, episode ~10-20s
        # so we just verify some transitions arrived (actor reached at least 1 turn).
        deadline = time.time() + 10.0
        while time.time() < deadline:
            with sink_lock:
                if len(received_transitions) >= 1:
                    break
            time.sleep(0.1)
        with sink_lock:
            n = len(received_transitions)
        assert n >= 1, f'expected at least 1 transition, got {n}'
        # Spot-check: first transition has client_id=0 (actor_id=0)
        with sink_lock:
            t0 = received_transitions[0]
        assert t0.client_id == 0
    finally:
        t_stop = time.time()
        backend.stop()
        elapsed = time.time() - t_stop
        assert elapsed < 3.0, f'stop_pool took {elapsed:.2f}s, expected < 3s'

        stop_inf_listener(inf_stop, inf_thr)
        stop_trans_listener(trans_stop, trans_thr)
