"""I29 P2.X — PPO paradigm Go pool e2e smoke。

验证 PPO Run loop 完整端到端:
- Python 起 InfServer socket listener(echo zero logits + value)+ Transition sink listener
- ctypes 调 start_pool_v2(paradigm='ppo')起 1 actor 跑 PPO with F1-D2 opp
- Go side actor 跑 PPO episodes,sample action with temperature → push transitions
- Python sink 收 ≥1 PPO transition + decode_ppo_payload 成功
- stop 干净 < 3s

Mac-only(libgicg_actor.dylib),smoke_full marker。
"""

from __future__ import annotations

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
from training.core.actor.transition_sink_wire import (
    Transition,
    decode_ppo_payload,
)


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _libs_built() -> bool:
    repo_root = Path(__file__).resolve().parents[4]
    ext = {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
    return all((repo_root / 'gicg_env' / f'lib{n}.{ext}').exists() for n in ('gicg', 'gicg_actor'))


@pytest.mark.smoke_full
@pytest.mark.skipif(not _libs_built(), reason='libgicg{,_actor} not built')
def test_ppo_go_actor_pool_e2e_smoke():
    inf_port = _free_port()
    trans_port = _free_port()

    # Echo callback:zero logits over 30 + zero value(stub V(s) head)
    def echo_zero_logits_with_value(req: InferRequest) -> InferResponse:
        return InferResponse(
            status=INFER_STATUS_OK,
            logits=np.zeros(30, dtype=np.float32),
            value=np.zeros(1, dtype=np.float32),  # PPO 需要 value 字段非空
        )

    received: list[Transition] = []
    sample_decode_errors: list[str] = []
    lock = threading.Lock()

    def sink(t: Transition) -> None:
        with lock:
            received.append(t)
        try:
            _ = decode_ppo_payload(t.payload)
        except Exception as exc:  # noqa: BLE001
            with lock:
                if len(sample_decode_errors) < 3:
                    sample_decode_errors.append(f'{type(exc).__name__}: {exc}')

    inf_ready = threading.Event()
    inf_stop = threading.Event()
    trans_ready = threading.Event()
    trans_stop = threading.Event()
    inf_thr = start_inf_listener(inf_port, echo_zero_logits_with_value, inf_ready, inf_stop)
    trans_thr = start_trans_listener(trans_port, sink, trans_ready, trans_stop)
    assert inf_ready.wait(timeout=2.0)
    assert trans_ready.wait(timeout=2.0)

    backend = GoActorBackend()
    paradigm_cfg = {
        'game_spec': {
            'pools': ['v_legacy'],
            'seed': 42,
            'players': [
                {'chars': [{'name': '赤蝶'}]},
                {'chars': [{'name': '墨客'}]},
            ],
        },
        'rollout_opponent': 'F1-D2',
        'gamma': 0.99,
        'gae_lambda': 0.95,
        'temperature': 1.0,
        'max_actions': 30,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': 42,
    }
    backend.start_with_config(
        paradigm='ppo',
        n_actors=1,
        inf_addr=f'127.0.0.1:{inf_port}',
        trans_addr=f'127.0.0.1:{trans_port}',
        paradigm_cfg=paradigm_cfg,
        io_timeout_ms=10_000,
    )
    try:
        deadline = time.time() + 10.0
        while time.time() < deadline:
            with lock:
                if len(received) >= 1:
                    break
            time.sleep(0.1)
        with lock:
            n = len(received)
            errs = list(sample_decode_errors)
        assert n >= 1, f'expected at least 1 PPO transition, got {n}'
        assert not errs, f'PPO decode errors: {errs}'
        with lock:
            t0 = received[0]
        assert t0.client_id == 0
        # Decode + verify shape
        ppo = decode_ppo_payload(t0.payload)
        # log_prob = log(softmax(zeros)[chosen]) over n_legal actions ≤ 0(prob ∈ (0,1])
        # First transition 通常 n_legal=1(select-active char 必选 1)→ log_prob=0
        assert ppo.log_prob <= 0.0, f'log_prob {ppo.log_prob} should be ≤ 0(log of prob)'
        assert ppo.value == pytest.approx(0.0), f'value should be 0(stub V(s) head)'
        assert ppo.n_legal >= 1
    finally:
        t_stop = time.time()
        backend.stop()
        elapsed = time.time() - t_stop
        assert elapsed < 3.0, f'stop_pool took {elapsed:.2f}s, expected < 3s'
        stop_inf_listener(inf_stop, inf_thr)
        stop_trans_listener(trans_stop, trans_thr)
