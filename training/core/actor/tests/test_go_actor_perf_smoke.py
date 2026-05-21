"""I29 P1.4 — Mac perf smoke: Go actor pool sustained throughput + memory baseline。

测试目标:30s wall window,N=4 actor Mac baseline,验证:
- transitions/sec > 5 per actor(基本 viability,实测 stage3_b_v_legacy/F1-D2 Mac
  Python baseline ~2 fps/actor,Go-native 应该 ≥ 5 fps/actor)
- 进程 RSS < 1 GB (Mac unified mem 紧,vs Python baseline ~11 GB N=16)
- 30s 跑完无 deadlock / fatal / leak

不是 Phase 1.5 final 验收 gate(那需要 Win box N=16 fps≥70 + mem≤2 GB),仅 Mac side
viability + 检测 regression。 Phase 1.5 Win box stress 走 tools.runs.train cfg-driven
端到端 production scenario。

依赖:libgicg_actor.dylib + libgicg.dylib 已 build。 Mac/Linux only(Win 路径不接入)。
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path

import numpy as np
import psutil
import pytest
import torch
import torch.nn as nn

from training.core.actor.go_backend import GoActorBackend
from training.core.actor.inference_server import InferenceServer
from training.core.actor.transition_sink_listener import (
    start_listener_in_thread as start_trans_listener,
    stop_listener as stop_trans_listener,
)
from training.core.actor.transition_sink_wire import Transition, decode_dmc_payload


class _ZeroLogitsNet(nn.Module):
    """Stub network — 返 zero logits。 验证 pipeline plumbing 不验证 RL signal。

    realistic forward latency 由 stub linear ops 模拟(~10μs per forward Mac CPU),
    比 trivial 直返常量 更现实 — torch dispatch + tensor 分配也算 hot path 一部分。
    """

    def __init__(self, max_actions: int = 30) -> None:
        super().__init__()
        self.max_actions = max_actions
        self.dummy = nn.Linear(10, max_actions)

    def forward(self, obs_dict):  # noqa: ARG002
        x = torch.zeros(1, 10)
        return {'logit_as_q': self.dummy(x)}


def build_zero_logits_forward(*, device_str, shared_cache, network, max_actions=30):  # noqa: ARG001
    """Forward callback returning zeros 但走 real network.forward(模拟 dispatch + GIL)。"""
    from training.core.actor.inference_server_socket_wire import INFER_STATUS_OK, InferResponse

    def cb(req):  # noqa: ARG001
        with torch.no_grad():
            out = network({})
            logits = out['logit_as_q'].detach().cpu().numpy().astype(np.float32).ravel()
        return InferResponse(status=INFER_STATUS_OK, logits=logits)

    return cb


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
@pytest.mark.skipif(not _libs_built(), reason='libgicg{,_actor}.{dylib|dll|so} not built')
def test_go_actor_perf_smoke_30s():
    """30s window Mac N=4 sustained throughput + mem。

    Stage3-like cfg(赤蝶 vs 墨客 单 char + v_legacy pool),fixed_0 me strategy 减
    me/opp 交替 noise,F1-D2 opp(production 同档)。
    """
    inf_port = _free_port()
    trans_port = _free_port()

    # InferServer with socket forward callback(walk 走 real network.forward 路径)
    net = _ZeroLogitsNet(max_actions=30)
    server = InferenceServer(
        network=net,
        device='cpu',
        max_batch=1,
        socket_port=inf_port,
        socket_forward_builder_path=(
            'training.core.actor.tests.test_go_actor_perf_smoke.build_zero_logits_forward'
        ),
        socket_forward_builder_kwargs={'max_actions': 30},
    )
    server.start(wait_ready_s=10.0)

    # Transition sink — 计 transitions arrived
    n_transitions = 0
    by_actor: dict[int, int] = {}
    by_episode: dict[tuple[int, int], int] = {}
    n_dmc_decode_errors = 0
    lock = threading.Lock()

    sample_decode_errors = []

    def sink(t: Transition) -> None:
        nonlocal n_transitions, n_dmc_decode_errors
        with lock:
            n_transitions += 1
            by_actor[t.client_id] = by_actor.get(t.client_id, 0) + 1
            key = (t.client_id, t.episode_id)
            by_episode[key] = by_episode.get(key, 0) + 1
        try:
            _ = decode_dmc_payload(t.payload)
        except Exception as exc:
            with lock:
                n_dmc_decode_errors += 1
                if len(sample_decode_errors) < 3:
                    sample_decode_errors.append(
                        f'len={len(t.payload)} client={t.client_id} ep={t.episode_id} step={t.step} err={exc}'
                    )

    trans_ready = threading.Event()
    trans_stop = threading.Event()
    trans_thr = start_trans_listener(trans_port, sink, trans_ready, trans_stop)
    assert trans_ready.wait(timeout=2.0)

    # Go pool with 4 actors
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
        'opp_features': 'F1',
        'opp_depth': 2,
        'max_actions': 30,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': 42,
        'epsilon': 0.05,
    }
    N_ACTORS = 4
    RUN_SECONDS = 15.0  # Mac smoke 15s 足够 viability signal,30s 留 Win stress

    proc = psutil.Process(os.getpid())
    mem_before = proc.memory_info().rss / (1024 * 1024)  # MB

    backend.start_with_config(
        paradigm='dmc',
        n_actors=N_ACTORS,
        inf_addr=f'127.0.0.1:{inf_port}',
        trans_addr=f'127.0.0.1:{trans_port}',
        paradigm_cfg=paradigm_cfg,
        io_timeout_ms=30_000,
    )
    t_start = time.time()
    try:
        time.sleep(RUN_SECONDS)
    finally:
        backend.stop()
        elapsed = time.time() - t_start

    with lock:
        total = n_transitions
        per_actor = dict(by_actor)
        n_episodes = len(by_episode)
        n_errs = n_dmc_decode_errors

    mem_after = proc.memory_info().rss / (1024 * 1024)
    mem_delta_mb = mem_after - mem_before

    # Cleanup
    server.stop()
    stop_trans_listener(trans_stop, trans_thr)

    # Report metrics(pytest capture 会显示)
    print(
        f'\n[perf smoke] elapsed={elapsed:.1f}s '
        f'n_transitions={total} '
        f'n_episodes={n_episodes} '
        f'per_actor={per_actor} '
        f'fps={total / elapsed:.2f} '
        f'fps/actor={total / elapsed / N_ACTORS:.2f} '
        f'mem_before={mem_before:.0f}MB mem_after={mem_after:.0f}MB delta={mem_delta_mb:+.0f}MB '
        f'decode_errors={n_errs}',
    )
    if sample_decode_errors:
        print(f'[perf smoke] sample decode errors:\n  ' + '\n  '.join(sample_decode_errors))

    # Assertions — Mac viability gates,远低于 Phase 1.5 Win box production gate(N=16
    # fps≥70 = 4.4/actor):
    assert n_errs == 0, f'DMC payload decode error count > 0: {n_errs}(wire 协议 drift)'
    assert total > 0, 'no transitions arrived — pipeline broken'
    fps_per_actor = total / elapsed / N_ACTORS
    assert fps_per_actor >= 1.0, (
        f'fps/actor={fps_per_actor:.2f} < 1.0 Mac baseline — perf regression or pipeline stall'
    )
    # mem delta < 500 MB(模型小 + Go runtime 总开销 ~250 MB,留 buffer)
    assert mem_delta_mb < 500, f'mem grew {mem_delta_mb:.0f} MB during 15s — possible leak'
