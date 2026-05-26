"""I29 redesign P2 — Mac perf smoke: Go subprocess collector sustained throughput baseline。

测试目标:15s wall window,N=4 actor Mac baseline,验证 I29 redesign 路径
(``DMCGoSubprocessCollector`` + cmd/gicg_actor subprocess + SHM ring + InfServer
mp.Process) 的 production-shape 端到端 fps:

- production decode→forward 路径真通 — 真 DMCNetwork(d_model=128)经 DMCInferenceNet
  wrap + Route A socket inference + SHM episode ring 到 master,与 sibling cgo path
  ``test_go_actor_perf_smoke.py`` 同等深度,但走 subprocess 路径(0 cgo lib in master)。
- fps/actor 报 — 与 ``test_python_mp_perf_smoke.py`` 同 scenario / pool /
  opponent_mix / network shape,做 fair comparison gate (Python mp baseline)。
- mem delta 报 — 不设 hard gate (subprocess 内部 mem 在子进程,master 侧 mem 主要
  是 InfServer mp.Process child + assembler 已 ready episodes 缓冲)。
- 15s 跑完无 deadlock / fatal。

不是 RL 信号 / training loop 测试 — 纯 collector throughput,与 Python mp baseline 严格
对齐(同 wall window + 同 paradigm cfg + 同 network shape)。

依赖:libgicg.dylib + bin/gicg_actor 已 build(test fixture 自动 build cmd/gicg_actor)。
Mac/Linux only(Win 路径 P1.4 未接入)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

from training.core.cfg import make_dmc_default_shape

# Go actor obs / logits 宽度 — 必须 == _build_dmc_network 的网络 action 容量,与 sibling
# cgo path 一致(make_dmc_default_shape().max_actions = 2048)。
_MAX_ACTIONS = make_dmc_default_shape().max_actions

# N_ACTORS + RUN_SECONDS 与 sibling cgo / Python mp test 一致 — fair comparison 要求。
# BENCH_N_ACTORS / BENCH_SEED env var 允许 bench harness 覆盖(run_mac_collector_pair
# 用 N=4 跑 5 seed)。
_DEFAULT_N_ACTORS = 4
_DEFAULT_SEED = 42
RUN_SECONDS = 15.0

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'


def _build_dmc_inference_net() -> Any:
    """Build production-shape DMCInferenceNet(wrap ActorCritic)for the perf smoke。

    与 ``test_go_actor_perf_smoke._build_dmc_network`` / ``test_python_mp_perf_smoke
    ._build_dmc_network`` 完全同 cfg:d_model=128 / n_cross_layers=2 / Stage3 production
    shape (IR obs schema)。 Subprocess path 需要 ``DMCInferenceNet`` 已 wrap
    (spawn_pipeline → InfServer.update_network 用 ``net.*`` 前缀 state_dict),与
    P1.4 5ep e2e test 同模式。
    """
    from training.core.network import AgentConfig
    from training.paradigms.dmc.inference_net import DMCInferenceNet
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
    net = DMCNetwork(agent_cfg, device='cpu', epsilon=0.05)
    return DMCInferenceNet(net.net)


def _libgicg_built() -> bool:
    """libgicg.dylib 存在即可(subprocess path 不需 libgicg_actor.dylib — Go binary
    自含 gicg_engine,master 只用 libgicg 由 InfServer mp.Process import gicg_env 间接
    加载,主进程 deal-breaker invariant #1 验过)。
    """
    ext = {'darwin': 'dylib', 'win32': 'dll'}.get(sys.platform, 'so')
    return (_REPO_ROOT / 'gicg_env' / f'libgicg.{ext}').exists()


@pytest.fixture(scope='module', autouse=True)
def build_go_binary():
    """Build cmd/gicg_actor once per module。 P1.4 path 不依赖 libgicg_actor.dylib —
    standalone Go subprocess 自含 gicg_engine。 mirror sibling 5ep e2e test fixture。
    """
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f'go build failed: {r.stderr}')


def _build_paradigm_config(n_actors: int, seed: int) -> dict[str, Any]:
    """Production stage3-shape paradigm cfg。 Mirror sibling
    ``test_go_subprocess_5ep_e2e._build_paradigm_config`` + ``test_go_actor_perf_smoke``
    paradigm_cfg(同 v_legacy pool)。

    Opponent mix — R6.3 (2026-05-25): production-fair mixed opp 三档,与
    sibling ``test_python_mp_perf_smoke.py:_build_mp_cfg`` 完全同 cfg(同
    weights:random=0.30/f1d2=0.50/f1d4=0.20,drop historical)。 R6.2 临时
    的 random=1.0 sanity 对齐已被 R6.3 production fair gate 取代 —
    ``mp_factories.py`` 现注册 ``f1d2``/``f1d4`` + ``_dmc_spec_sampler``
    从 ``cfg.opp_mix`` weighted 抽样,故 Python mp 真跑 mixed,Go side bench
    也回到 production mixed-opp。 historical 两侧统一 drop (Go side 是 proxy,
    Python 端无等价)。 my_player_strategy='fixed_0' 与 cgo path 一致 — 减 me/opp
    交替 noise。
    """
    return {
        'game_spec': {
            'pools': ['v_legacy'],
            'seed': int(seed),
            'players': [
                {'chars': [{'name': '赤蝶'}]},
                {'chars': [{'name': '墨客'}]},
            ],
        },
        'opponent_mix': {'random': 0.30, 'f1d2': 0.50, 'f1d4': 0.20},
        'max_actions': _MAX_ACTIONS,
        'max_episode_steps': 360,
        'my_player_strategy': 'fixed_0',
        'base_seed': int(seed),
        'epsilon': 0.05,
    }


@pytest.mark.smoke_full
@pytest.mark.skipif(not _libgicg_built(), reason='libgicg.{dylib|dll|so} not built')
def test_go_subprocess_perf_smoke_15s():
    """15s window Mac N_ACTORS (or BENCH_N_ACTORS) Go subprocess throughput baseline。

    Stage3-like cfg(赤蝶 vs 墨客 单 char + v_legacy pool),production opponent_mix
    (random=0.2/f1d2=0.3/f1d4=0.2/historical=0.3),与 cgo sibling perf smoke 同 cfg。

    Pure collector bench:bootstrap DMCGoSubprocessCollector → single collect() with
    big n_episodes + 15s deadline → drain → 报 fps_total / fps_per_actor /
    mem_delta / n_episodes。 无 training loop — 只测 actor pool 产 transition 速率
    (与 Python mp test 同).

    BENCH_N_ACTORS env var 覆盖 N_ACTORS(bench harness 多 seed 跑)。
    BENCH_SEED env var 覆盖 seed(bench harness 多 seed 跑)。
    BENCH_GOMAXPROCS env var 覆盖 go_gomaxprocs (默认 = PipelineTuningCfg.go_gomaxprocs default,
    post-D6 = 1)。 sweep GOMAXPROCS (1/2/4) verify Stage 1 D6 fix 是否最优。
    """
    from training.paradigms.dmc.go_subprocess_collector import DMCGoSubprocessCollector

    n_actors = int(os.environ.get('BENCH_N_ACTORS', str(_DEFAULT_N_ACTORS)))
    seed = int(os.environ.get('BENCH_SEED', str(_DEFAULT_SEED)))
    gomaxprocs_override = os.environ.get('BENCH_GOMAXPROCS')
    run_seconds = float(os.environ.get('BENCH_RUN_SECONDS', str(RUN_SECONDS)))

    network = _build_dmc_inference_net()
    paradigm_cfg = _build_paradigm_config(n_actors=n_actors, seed=seed)

    # cfg stub — DMCGoSubprocessCollector __init__ 不读 cfg.pipeline / cfg.scenario(那些
    # wire 由 _make_go_collector 在 cfg → paradigm_cfg_dict 时已映射);此处 cfg 仅
    # placeholder 保 signature 兼容,与 5ep e2e test 同模式。
    class _CfgStub:
        pass

    cfg_stub = _CfgStub()

    # SHM sizing 同 5ep e2e (4 MB slot × 8 cap = 32 MB,Mac 可承);ready_timeout 30s
    # 给 InfServer torch import + spawn(~3-5s cold) + Go inf TCP connect headroom。
    # io_timeout 30s production 一致。 collect_deadline_s = RUN_SECONDS — collect()
    # 内 poll deadline 即 perf window。
    from training.core.actor.pipeline_tuning_cfg import PipelineTuningCfg

    # GOMAXPROCS override (BENCH_GOMAXPROCS env var):None → PipelineTuningCfg default
    # (post-D6 = 1);显式数字 → sweep。 注意 0 也是 valid value (Go runtime auto = NumCPU)。
    tuning_kwargs: dict = dict(
        shm_capacity=8,
        shm_slot_size=4 * 1024 * 1024,
        inf_max_batch=n_actors,
        inf_batch_timeout_ms=2,
        ready_timeout_s=30.0,
        io_timeout_ms=30_000,
        device='cpu',
        collect_deadline_s=run_seconds,
    )
    if gomaxprocs_override is not None:
        tuning_kwargs['go_gomaxprocs'] = int(gomaxprocs_override)

    collector = DMCGoSubprocessCollector(
        cfg=cfg_stub,
        network=network,
        paradigm_cfg_dict=paradigm_cfg,
        n_actors=n_actors,
        tuning=PipelineTuningCfg(**tuning_kwargs),
    )

    # Bootstrap excluded from window — cold-start InfServer (~3-5s torch import +
    # spawn) + Go subprocess READY (~500ms) 是固定 overhead,不属 perf 计量。
    collector._bootstrap()

    proc = psutil.Process(os.getpid())
    mem_before = proc.memory_info().rss / (1024 * 1024)  # MB

    t_start = time.time()
    n_transitions = 0
    n_episodes = 0
    elapsed = 0.0

    try:
        # 一次 collect() 内部 poll SHM 15s(target n_episodes 给极大数 → 永远不达 →
        # deadline 到点 drain_ready 返回累计);与 sibling 模式不同(cgo path 是 listener
        # thread 后台收 + 主 sleep,subprocess path 是 collect 主动 poll)— 但 wall
        # window 一致 (15s),fair comparison 成立。
        out = collector.collect(n_episodes=1_000_000)
        elapsed = time.time() - t_start
        n_transitions = int(out.runtime_metrics.get('n_dmc_transitions', 0))
        n_episodes = int(out.runtime_metrics.get('n_dmc_episodes', 0))
    finally:
        if elapsed == 0.0:
            elapsed = time.time() - t_start
        collector.close()

    mem_after = proc.memory_info().rss / (1024 * 1024)
    mem_delta_mb = mem_after - mem_before

    fps_total = n_transitions / elapsed if elapsed > 0 else 0.0
    fps_per_actor = fps_total / n_actors if n_actors > 0 else 0.0

    # decode_errors — go_subprocess_collector decode SHM frame 内部异常会打 stderr 但
    # 不计数(continue drop frame);此处 decode_errors=0 报,与 cgo path output 行格式
    # 对齐(run_mac_collector_pair _RE_GO 解析此字段)。
    print(
        f'\n[perf smoke] elapsed={elapsed:.1f}s '
        f'n_transitions={n_transitions} '
        f'n_episodes={n_episodes} '
        f'fps={fps_total:.2f} '
        f'fps/actor={fps_per_actor:.2f} '
        f'mem_before={mem_before:.0f}MB mem_after={mem_after:.0f}MB delta={mem_delta_mb:+.0f}MB '
        f'decode_errors=0',
    )

    # Correctness gate — pipeline 必须流通,否则 fps=0 是 deadlock/fatal 静默。
    assert n_transitions > 0, (
        f'no transitions arrived in {run_seconds}s — subprocess pipeline broken '
        '(check libgicg.dylib, bin/gicg_actor, InfServer startup, SHM ring wiring)'
    )
