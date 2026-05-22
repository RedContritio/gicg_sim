"""I29 — Mac perf smoke: Go actor pool sustained throughput + memory baseline。

测试目标:15s wall window,N=4 actor Mac baseline,验证:
- production decode→forward 路径端到端真通 — 真 DMCNetwork(d_model=128)+ 真
  build_dmc_socket_forward_callback(T-R2:此前 Phase 1 smoke 全用 stub 绕过)
- fps/actor ≥ 2.5(实测真网络 max_actions=2048,正常 5.6-7.0;偶发不稳定见 gate 注释)
- mem delta < 500 MB(无 leak)
- 15s 跑完无 deadlock / fatal,decode_errors == 0

不是 Phase 1.5 final 验收 gate(那需要 Win box N=16 fps≥70 + mem≤2 GB),仅 Mac side
viability + regression 检测 + production forward 路径 correctness。 Phase 1.5 Win box
stress 走 tools.runs.train cfg-driven 端到端 production scenario。

依赖:libgicg_actor.dylib + libgicg.dylib 已 build。 Mac/Linux only(Win 路径不接入)。
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from training.core.actor.go_backend import GoActorBackend
from training.core.actor.inference_server import InferenceServer
from training.core.actor.transition_sink_listener import (
    start_listener_in_thread as start_trans_listener,
    stop_listener as stop_trans_listener,
)
from training.core.actor.transition_sink_wire import Transition, decode_dmc_payload
from training.core.cfg import make_dmc_default_shape

# Go actor obs / logits 宽度 — 必须 == _build_dmc_network 的网络 action 容量,否则
# 真实 n_legal > 此值时 chosen_action 越出 logits 宽 → 训练 gather OOB(I29 T-R3 bug)。
_MAX_ACTIONS = make_dmc_default_shape().max_actions


def _build_dmc_network() -> Any:
    """Build a production-shape DMCNetwork for the perf smoke。

    T-R2:perf smoke 不再用 stub forward。 走真 DMCNetwork + 真
    ``build_dmc_socket_forward_callback`` — 端到端验证 production decode→forward
    路径(socket InferRequest → decode_dmc_request → DMCInferenceNet.forward),
    此前 Phase 1 Mac smoke 全用 stub 绕过该路径。

    结构维度取 IR obs schema 固定常量(``make_dmc_default_shape``);d_model /
    n_cross_layers 用 Stage3 生产值(stage3_b_v_legacy.toml:128 / 2),使 Mac
    perf 数据反映真实模型规模而非 toy。
    """
    from training.core.network import AgentConfig
    from training.paradigms.dmc.network import DMCNetwork

    shape = make_dmc_default_shape()
    agent_cfg = AgentConfig(
        n_counter_slots=shape.n_counter_slots,
        n_hooks=shape.n_hooks,
        max_ops_per_hook=shape.max_ops_per_hook,
        max_actions=shape.max_actions,
        d_model=128,
        n_cross_layers=2,
    )
    return DMCNetwork(agent_cfg, device='cpu', epsilon=0.05)


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

    # InferServer with production socket forward — 真 DMCNetwork + 真
    # build_dmc_socket_forward_callback(socket decode → DMCInferenceNet.forward)。
    net = _build_dmc_network()
    server = InferenceServer(
        network=net,
        device='cpu',
        max_batch=1,
        socket_port=inf_port,
        socket_forward_builder_path='training.paradigms.dmc._socket_decoder.build_dmc_socket_forward_callback',
        socket_forward_builder_kwargs={'max_actions': _MAX_ACTIONS},
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
        'max_actions': _MAX_ACTIONS,
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
    # 实测(真 DMCNetwork d_model=128,N=4 Mac,max_actions=2048):正常 ~5.6-7.0
    # fps/actor。 gate 2.5 是回归 floor。 已知 intermittent 不稳定(偶发 mem 膨胀 →
    # fps 骤降,I29 T-R5 follow-up 待查)会触发此 gate — 属预期信号,非误报。
    assert fps_per_actor >= 2.5, (
        f'fps/actor={fps_per_actor:.2f} < 2.5 Mac real-net baseline — perf regression or pipeline stall'
    )
    # mem delta < 500 MB(模型小 + Go runtime 总开销 ~250 MB,留 buffer)
    assert mem_delta_mb < 500, f'mem grew {mem_delta_mb:.0f} MB during 15s — possible leak'
