"""I29 T-C1 Mac fair bench — Python mp actor pool sustained throughput baseline。

测试目标:15s wall window,N=4 actor Mac baseline,验证:
- production forward 路径端到端真通 — 真 DMCNetwork(d_model=128)经
  DMCInferenceNet wrap + InferenceServer 批处理 + _DMCObsDictRemoteProvider
  numpy IPC(与 Go-actor test 同等路径深度)
- fps/actor 报 — 与 test_go_actor_perf_smoke 同 scenario / card_pool /
  opponent_mix / network shape,做 fair comparison baseline
- mem delta 报 — 不设 hard gate,供 bench 对比

不设 fps gate(benchmark 不是回归守门);只验证 pipeline 端到端通、
decode_errors == 0、transitions > 0。

设计约束:
- 同 test_go_actor_perf_smoke 的 N_ACTORS / RUN_SECONDS / _build_dmc_network
- 不 stub 网络(真 DMCNetwork d_model=128)
- 不走全 pipeline(无 training loop overhead — 只测 collector 产 transition 速率)
- 依赖:libgicg.dylib 已 build(mp actor 用 GicgEnv; gicg_actor.dylib 可无)。
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from training.core.cfg import make_dmc_default_shape

_MAX_ACTIONS = make_dmc_default_shape().max_actions

# N_ACTORS + RUN_SECONDS 与 test_go_actor_perf_smoke 一致 — fair comparison 要求。
# BENCH_N_ACTORS env var 允许 bench harness 覆盖(bench harness 用 N=4 和 N=8 对比)。
_DEFAULT_N_ACTORS = 4
_DEFAULT_SEED = 42
RUN_SECONDS = 15.0


def _build_dmc_network() -> Any:
    """Build a production-shape DMCNetwork for the perf smoke。

    与 test_go_actor_perf_smoke._build_dmc_network 完全同 cfg:
    d_model=128 / n_cross_layers=2 / Stage3 production shape。
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


def _libgicg_built() -> bool:
    """libgicg.dylib 存在即可(mp actor 用 GicgEnv;不需 gicg_actor.dylib)。"""
    repo_root = Path(__file__).resolve().parents[4]
    ext = {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
    return (repo_root / 'gicg_env' / f'libgicg.{ext}').exists()


def _build_mp_cfg(n_actors: int, seed: int = 42) -> Any:
    """Build a TrainingConfig matching Mac bench scenario for N actors。

    Matches bench_v_legacy_mac_python_mp.toml scenario / opponent_mix /
    network shape — same as test_go_actor_perf_smoke paradigm_cfg。
    """
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    # Full v_legacy 26-card pool — production bench card list
    card_pool = [
        '乘胜追击',
        '以攻代守',
        '以牙还牙',
        '以逸待劳',
        '伏兵之术',
        '佛跳墙',
        '刺刺猫爪',
        '占星',
        '反制',
        '发现静电',
        '守正',
        '星愿',
        '清洁时间',
        '玄冰',
        '瞬身之术',
        '碌碌无为',
        '美味烧鸡',
        '荷花酥',
        '蝶鳞',
        '西风剑',
        '西风长枪',
        '诅咒',
        '速速茶点',
        '铁剑',
        '铁弓',
        '铁枪',
    ]

    paradigm_dict = {
        # Mp factory paths — required by _bootstrap
        'mp_env_factory_path': 'training.paradigms.dmc.mp_factories.build_dmc_env_factory',
        'mp_opp_registry_path': 'training.paradigms.dmc.mp_factories.build_dmc_opp_registry',
        'mp_provider_path': 'training.paradigms.dmc.mp_factories.build_dmc_provider',
        # Algorithm + shape — match production bench
        'lr': 5e-5,
        'batch_size': 16,
        'buffer_cap': 50_000,
        'max_grad_norm': 1.0,
        'total_frames': 999_999_999,  # pure collector; no train loop terminates by frames
        'eval_interval_episodes': 999_999_999,
        'eval_baselines': [],
        'agent': {
            'd_model': 128,
            'n_cross_layers': 2,
        },
        # R6.3 (2026-05-25): production-fair mixed opp 三档 (drop
        # historical — mp_factories.py 不注册 historical;Go side
        # historical 是 cost-faithful proxy 而 Python 端无等价;两侧统一
        # 不含 historical 才公平)。 weights = 0.3 / 0.5 / 0.2 (经验偏 f1d2
        # — depth-2 minimax 是产线 mix 中最高频 opp;f1d4 仅 20% 因
        # ~28K DeepCopy/turn 巨贵;random 30% 留 baseline)。 historical=0.0
        # 显式给出让 OpponentMixCfg 的 sum=1.0 validation 通过。
        # Phase 1 调查发现 Phase 2 R6.2 sanity bench (random=1.0) 不能反映
        # production workload,R6.3 重新解锁三档 mixed-opp。
        'opponent_mix': {
            'random': 0.30,
            'f1d2': 0.50,
            'f1d4': 0.20,
            'historical': 0.0,
            'ring_size': 8,
        },
    }

    return TrainingConfig(
        meta=MetaCfg(
            seed=seed,
            paradigm='dmc',
            run_label='mp_perf_smoke',
            device='cpu',
        ),
        pipeline=PipelineCfg(
            mode='async',
            num_actors=n_actors,
            actor_backend='python',
        ),
        scenario=ScenarioCfg(
            team_0=['赤蝶'],
            team_1=['墨客'],
            pool=['v_legacy'],
            card_pool=card_pool,
            team_size=1,
            max_rounds=15,
            deck_padding={'card': '碌碌无为', 'target_size': 15},
            data_dir='data',
        ),
        paradigm=paradigm_dict,
        checkpoint=CheckpointCfg(save_every=999_999_999, keep_last_n=1, artifacts_root='artifacts'),
    )


@pytest.mark.smoke_full
@pytest.mark.skipif(not _libgicg_built(), reason='libgicg.{dylib|dll|so} not built')
def test_python_mp_perf_smoke_15s():
    """15s window Mac N=4 (or BENCH_N_ACTORS) Python mp throughput baseline。

    Stage3-like cfg(赤蝶 vs 墨客 单 char + v_legacy pool),production
    opponent_mix(random=0.20/f1d2=0.30/f1d4=0.20/historical=0.30)。

    Pure collector bench:bootstrap DMCMultiProcessCollector → drain ring
    loop for 15s → 报 fps_total / fps_per_actor / mem_delta / n_episodes。
    无 training loop — 只测 actor pool 产 transition 速率。

    BENCH_N_ACTORS env var 覆盖 N_ACTORS(bench harness 用于 N=4 / N=8 对比)。
    BENCH_SEED env var 覆盖 seed(bench harness 跑多 seed 时使用)。
    """
    n_actors = int(os.environ.get('BENCH_N_ACTORS', str(_DEFAULT_N_ACTORS)))
    seed = int(os.environ.get('BENCH_SEED', str(_DEFAULT_SEED)))
    run_seconds = float(os.environ.get('BENCH_RUN_SECONDS', str(RUN_SECONDS)))

    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    cfg = _build_mp_cfg(n_actors=n_actors, seed=seed)
    net = _build_dmc_network()

    # DMCMultiProcessCollector 需要 opp_pool 但 mp mode 用 _spawn_inference_pool 和
    # actor factories — opp_pool 在 bootstrap 中不直接用。传 None 即可(actors 走 mp
    # factory 路径,不读 parent opp_pool)。
    collector = DMCMultiProcessCollector(
        cfg=cfg,
        paradigm_cfg=None,  # _bootstrap 不读(actor 侧读 cfg.paradigm dict)
        network=net,
        opp_pool=None,  # mp mode: actors 走 mp factory;opp_pool = parent unused
        env_factory=None,  # mp mode: actors 走 mp factory
    )

    proc = psutil.Process(os.getpid())
    mem_before = proc.memory_info().rss / (1024 * 1024)  # MB

    # Bootstrap — starts InferenceServer + N actor mp.Process workers
    # _bootstrap is idempotent; first call does the real work.
    collector._bootstrap()
    N_ACTORS = n_actors  # for print below

    t_start = time.time()
    n_transitions = 0
    n_episodes = 0

    try:
        # Drain ring continuously for RUN_SECONDS — pure throughput measurement.
        # No training step; just absorb what actors produce.
        deadline = t_start + run_seconds
        while time.time() < deadline:
            item = collector.ring.try_pop()
            if item is None:
                # Ring empty — brief yield to avoid busy-spin burning a core
                time.sleep(0.001)
                continue
            # item is an EpisodeRecord (push_episode_record=True in _bootstrap)
            transitions = getattr(item, 'transitions', item)
            n_transitions += len(transitions)
            n_episodes += 1
    finally:
        elapsed = time.time() - t_start
        collector.close()

    mem_after = proc.memory_info().rss / (1024 * 1024)
    mem_delta_mb = mem_after - mem_before

    fps_total = n_transitions / elapsed if elapsed > 0 else 0
    fps_per_actor = fps_total / N_ACTORS

    print(
        f'\n[py-mp perf smoke] elapsed={elapsed:.1f}s '
        f'n_transitions={n_transitions} '
        f'n_episodes={n_episodes} '
        f'fps={fps_total:.2f} '
        f'fps/actor={fps_per_actor:.2f} '
        f'mem_before={mem_before:.0f}MB mem_after={mem_after:.0f}MB delta={mem_delta_mb:+.0f}MB',
    )

    # Correctness gate — pipeline must flow transitions
    assert n_transitions > 0, (
        f'no transitions arrived in {run_seconds}s — Python mp pipeline broken '
        '(check libgicg.dylib, InferenceServer startup, SHMRing wiring)'
    )
