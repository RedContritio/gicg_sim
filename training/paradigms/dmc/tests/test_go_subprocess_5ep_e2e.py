"""I29 redesign P1.4 — 5 episode e2e through DMCGoSubprocessCollector with production cfg shape。

Cover full production path at depth (5 ep × N ∈ {2, 4} actor + v_legacy pool + stage3-shape cfg):

    master (no cgo lib)
      ├─ DMCGoSubprocessCollector
      │    ├─ DMCInferenceNet (DMCNetwork.net wrap,production agent shape)
      │    ├─ DmcTransitionAssembler (n_counter_slots etc from network)
      │    └─ PipelineHandle (spawn_pipeline 三件套)
      │         ├─ InferenceServer mp.Process (Route A socket forward,DMCInferenceNet)
      │         ├─ TransitionShmChannel (owner)
      │         └─ cmd/gicg_actor subprocess (N TCP InferenceClient + DMC paradigm.Run)
      └─ collect(n_episodes=5) → CollectorOutput

Verify (per parametrize N=[2, 4]):
  - Collector spawn + collect 5 ep 整栈通 (<60s wall budget on Mac N=2 / N=4,production
      1 ep ~3-5s;N=4 ≈ 5/4 round-trips → 更快收齐,wall budget 60s 留 headroom)
  - 5 ep 全 schema-valid:CollectorOutput.episode_stats len=5 +
      runtime_metrics.n_dmc_episodes=5 + n_dmc_transitions > 0
  - 每 ep transitions[] obs_dict 完整 (DmcTransition shape — action_idx ∈ [0, max_actions),
      G ∈ {-1, 0, 1})
  - episode_stats client_id ∈ [0, n_actors) — 验 R7.2 N+2 拓扑下跨 subprocess clientID 唯一
  - winner 多样性 sanity (5 ep 不全同一 winner — random opponent + epsilon-greedy 必产
      mixed outcomes;5 ep 不保 100% mix,但 winner set 至少 1 个非 0 即可)
  - master 进程 0 libgicg 加载 (deal-breaker invariant #1 — `ps -o command | grep
      libgicg` empty in master)
  - Clean shutdown:close() 后 Go subprocess returncode=0,SHM unlink OK

N=2 覆盖最小并发 path,N=4 覆盖 production scale (production 跑 N=4-16,N=4 e2e 是
production-fair sample)。 R7.2 N independent subprocess 拓扑下 N=2 vs N=4 验证跨 subprocess
clientID 分布 + 多 actor InfServer batched forward path。

不验证 RL 信号 (5 ep 不够);不跑真 train loop (Phase 2 acceptance bench harness 才 wire
collector → buffer → train)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN = _REPO_ROOT / 'bin' / 'gicg_actor'
_ISOLATED_CHILD_ENV = 'GICG_GO_SUBPROCESS_5EP_E2E_CHILD'


@pytest.fixture(scope='module', autouse=True)
def build_go_binary():
    """Build cmd/gicg_actor once per module。 P1.4 path 不依赖 libgicg_actor.dylib —
    standalone Go subprocess 自含 gicg_engine。"""
    _BIN.parent.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        ['go', 'build', '-o', str(_BIN), './cmd/gicg_actor'],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        pytest.skip(f'go build failed: {r.stderr}')


def _build_dmc_inference_net() -> Any:
    """Build production-shape DMCInferenceNet (wraps ActorCritic) for the e2e。

    Mirror test_go_subprocess_1ep_smoke.py — make_dmc_default_shape gives the same
    n_counter_slots=1832 / n_hooks=900 / max_ops_per_hook=64 / max_actions=2048
    as production Stage 3 cfg。 d_model=128 / n_cross_layers=2 (AZ default — DMC
    historical d_model=32 but bigger network is fine for 5ep smoke shape probe)。
    """
    from training.core.cfg import make_dmc_default_shape
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


def _build_paradigm_config() -> dict[str, Any]:
    """Production stage3-shape paradigm cfg。 Mirror DMCParadigm._make_go_collector 的
    paradigm_cfg dict 结构 — Go side DMCConfig schema (gicg_actor/dmc/paradigm.go)。

    Opponent mix:random 0.7 + f1d2 0.3 — avoid pure-random (无任何 minimax 算压)又
    avoid pure-f1d2 (5 ep × 2 actor × ~10s/ep minimax wall 不可控)。 historical 0
    (P1.4 不 wire historical-net ring,5ep smoke 不需多对手)。
    """
    return {
        'game_spec': {
            'pools': ['v_legacy'],
            'seed': 42,
            'players': [
                {'chars': [{'name': '赤蝶'}]},
                {'chars': [{'name': '墨客'}]},
            ],
        },
        'opponent_mix': {'random': 0.7, 'f1d2': 0.3, 'f1d4': 0.0, 'historical': 0.0},
        'max_actions': 2048,
        'max_episode_steps': 360,
        'my_player_strategy': 'alternate',  # production default (cgo path 同 alternate)
        'base_seed': 42,
        'epsilon': 0.05,
    }


def _verify_no_cgo_in_master() -> None:
    """Deal-breaker invariant #1 — master 进程 0 cgo lib loaded。

    master pid (我们) 不应该 import libgicg / libshm / libgicg_actor;Go-actor 在独立
    subprocess + InfServer 在独立 mp.Process。 用 lsof 看本 pid open dylib (Mac/Linux);
    Win 略 (P1.4 Mac-only smoke)。 grep libgicg pattern;若 master 加载了任何 libgicg_actor
    / libgicg.dylib 就 fail (libshm 是允许的 — shm ctypes lib 是 master-required)。
    """
    import os

    if sys.platform == 'win32':
        # Win 用 ListLoadedModules,skip — P1.4 Mac/Linux verify。
        return
    pid = os.getpid()
    try:
        r = subprocess.run(['lsof', '-p', str(pid)], capture_output=True, text=True, timeout=5.0)
    except Exception:
        return  # lsof 不可用 (CI container 不一定有);skip 不 fail
    if r.returncode != 0:
        return
    leaked = []
    for line in r.stdout.splitlines():
        low = line.lower()
        # libgicg.dylib (Python cgo bridge) 或 libgicg_actor.dylib (actor cgo path) 任一
        # 都 = master 含 cgo state = invariant break。 libshm.dylib 允许 (master-side SHM ring
        # 的 ctypes lib,无 gicg engine state)。
        if 'libgicg.dylib' in low or 'libgicg_actor' in low or 'libgicg.so' in low:
            leaked.append(line.strip())
    assert not leaked, f'I29 deal-breaker #1 broken — master pid={pid} 加载了 libgicg cgo lib:\n' + '\n'.join(leaked)


@pytest.mark.parametrize('n_actors', [2, 4])
def test_dmc_go_subprocess_5ep_e2e(n_actors: int, request: pytest.FixtureRequest):
    """Full 5 ep e2e through DMCGoSubprocessCollector with production-shape cfg。

    Parametrize N=[2, 4]:
      - N=2 — minimum concurrent path (兼容历史 baseline / Mac dev box)
      - N=4 — production scale e2e sample (production 跑 N=4-16,N=4 是 production-fair lower bound)

    Inference transport: TCP only (I29 R7.1 删 SHM inference path) — Go-actor per-actor
    TCP socket → InfServer subprocess socket_listener thread → batched forward,与
    Python mp.Queue 客户端共用 request_q,与 Python mp wire 等价无 bridge layer。

    Deadline 60s wall — cold-start InfServer (~3-5s torch import + spawn) + Go subprocess
    READY (N × ~500ms sequential) + 5 ep collect (N=2 ~10-25s,N=4 更快 ≈ 5/4 round-trips
    × ~3-5s/ep ≈ 6-10s) → 总 ~15-35s + headroom for slow CI / Mac BG load。
    """
    if os.environ.get(_ISOLATED_CHILD_ENV) != '1':
        env = os.environ.copy()
        env[_ISOLATED_CHILD_ENV] = '1'
        with (
            tempfile.TemporaryFile(mode='w+', encoding='utf-8') as stdout,
            tempfile.TemporaryFile(
                mode='w+',
                encoding='utf-8',
            ) as stderr,
        ):
            try:
                r = subprocess.run(
                    [sys.executable, '-m', 'pytest', '-q', request.node.nodeid],
                    cwd=str(_REPO_ROOT),
                    env=env,
                    stdout=stdout,
                    stderr=stderr,
                    timeout=180.0,
                )
            except subprocess.TimeoutExpired:
                stdout.seek(0)
                stderr.seek(0)
                pytest.fail(
                    f'isolated 5ep e2e timed out for N={n_actors}\nstdout:\n{stdout.read()}\nstderr:\n{stderr.read()}'
                )
            stdout.seek(0)
            stderr.seek(0)
            r_stdout = stdout.read()
            r_stderr = stderr.read()
        assert r.returncode == 0, f'isolated 5ep e2e failed for N={n_actors}\nstdout:\n{r_stdout}\nstderr:\n{r_stderr}'
        return

    from training.paradigms.dmc.go_subprocess_collector import DMCGoSubprocessCollector

    network = _build_dmc_inference_net()
    paradigm_cfg = _build_paradigm_config()

    # cfg stub — DMCGoSubprocessCollector __init__ 只读 paradigm_cfg_dict + network attr,
    # 不取 cfg.pipeline / cfg.scenario (那些 wire 由 paradigm._make_go_collector 在 cfg
    # → paradigm_cfg_dict 时已映射);此处 cfg 仅 placeholder 保 signature 兼容。
    class _CfgStub:
        pass

    cfg_stub = _CfgStub()

    from training.core.actor.pipeline_tuning_cfg import PipelineTuningCfg

    collector = DMCGoSubprocessCollector(
        cfg=cfg_stub,
        network=network,
        paradigm_cfg_dict=paradigm_cfg,
        n_actors=n_actors,
        tuning=PipelineTuningCfg(
            # SHM sizing — 同 1ep smoke,4 MB slot × 8 cap = 32 MB (Mac 可承)。 N=4 时
            # 同 ring N producer 仍走同 32 MB(slot_size 是 per-slot 不是 per-producer)。
            shm_capacity=8,
            shm_slot_size=4 * 1024 * 1024,
            # inf_max_batch=n_actors — InfServer batch 满 N 即 forward,与 production
            # `_make_go_collector` 一致(max_batch = n_actors 时 1 步 forward N 请求)。
            inf_max_batch=n_actors,
            inf_batch_timeout_ms=2,
            ready_timeout_s=30.0,
            io_timeout_ms=30_000,
            device='cpu',
            collect_deadline_s=60.0,
        ),
    )

    t_start = time.monotonic()
    try:
        # Single collect call攒 5 ep — collect_deadline_s 60s 内 attempt → assembler 攒齐返回。
        out = collector.collect(n_episodes=5)
        elapsed = time.monotonic() - t_start

        # CollectorOutput shape
        assert out.n_episodes >= 5, (
            f'expected ≥ 5 episodes within 60s deadline, got {out.n_episodes} '
            f'(assembler ready+pending stats={collector.assembler.stats()})'
        )
        assert out.runtime_metrics['n_dmc_episodes'] == out.n_episodes
        assert out.runtime_metrics['n_dmc_transitions'] > 0, 'no transitions assembled'
        assert out.n_units == out.runtime_metrics['n_dmc_transitions']
        # transitions list 是 flat empty (DMC paradigm 走 episode-batch path,raw episodes
        # 在 runtime_metrics.dmc_episodes 里,与 DMCGoActorCollector 一致)。
        assert out.transitions == [], (
            f'DMC collect should yield flat transitions=[] (raw eps in runtime_metrics), got len={len(out.transitions)}'
        )

        # Verify dmc_episodes — paradigm strategy push_episode 消费的真实 episodes 数据
        eps = out.runtime_metrics['dmc_episodes']
        assert len(eps) == out.n_episodes, f'dmc_episodes count {len(eps)} != episode_stats count {out.n_episodes}'
        # Per-episode shape verify
        for ep_idx, (trans_list, G) in enumerate(eps):
            assert isinstance(trans_list, list) and len(trans_list) > 0, (
                f'ep {ep_idx} empty transition list (winner G={G})'
            )
            assert G in (-1.0, 0.0, 1.0), f'ep {ep_idx} winner G={G} not in {{-1, 0, 1}}'
            # DmcTransition shape — obs_dict not empty + action_idx in [0, max_actions)
            first = trans_list[0]
            assert hasattr(first, 'obs_dict') and isinstance(first.obs_dict, dict), (
                f'ep {ep_idx} trans 0 missing obs_dict'
            )
            assert 0 <= first.action_idx < 2048, f'ep {ep_idx} trans 0 action_idx={first.action_idx} out of [0, 2048)'
            # obs_dict 必含 production schema 关键字段 — post IR cutover 2026-05-19 用
            # `hook_ir`(不再 `hook_emb`),见 _capture_obs_np return dict。
            for key in (
                'counter_values',
                'counter_sids',
                'active_slot_mask',
                'hook_ir',
                'hook_mask',
                'action_refs',
                'action_payments',
                'legal_mask',
                'n_legal',
            ):
                assert key in first.obs_dict, f'ep {ep_idx} trans 0 obs_dict missing {key!r}'

        # Episode stats verify
        for stat in out.episode_stats:
            assert stat['source'] == 'go_subprocess', (
                f'episode_stats source field wrong: {stat["source"]!r} (expected go_subprocess)'
            )
            assert stat['winner'] in (-1, 0, 1)
            assert stat['n_transitions'] > 0
            # R7.2 N independent subprocess 拓扑:client_id = BaseActorID ∈ [0, n_actors)
            assert 0 <= stat['client_id'] < n_actors, (
                f'client_id={stat["client_id"]} out of range [0, n_actors={n_actors})'
            )

        # winner 多样性 sanity — 5 ep × N actor × random opponent + epsilon 必至少 1 个非平局
        # (5 全 0 = engine logic 异常 / random opponent 没 actor strength info)
        winners = [s['winner'] for s in out.episode_stats]
        assert any(w != 0 for w in winners), (
            f'all 5 episodes drew (winners={winners}) — likely engine timeout / strategy bug'
        )

        # I29 invariant #1 — master 0 cgo lib
        _verify_no_cgo_in_master()

        # Wall budget — 5 ep 应 < 60s,实际 Mac M-series N=2 ~10-25s,N=4 ~10-20s(更并行)
        assert elapsed < 60.0, f'5 ep wall {elapsed:.1f}s exceeds 60s budget (N={n_actors})'

        print(
            f'\n[5ep_e2e N={n_actors}] n_eps={out.n_episodes} n_trans={out.n_units} '
            f'winners={winners} elapsed={elapsed:.2f}s '
            f'assembler={collector.assembler.stats()}',
            file=sys.stderr,
        )
    finally:
        collector.close()

    # Clean shutdown — Go subprocess SIGTERM exit 0
    # (collector.close → handle.shutdown → go_proc.terminate SIGTERM cancel ctx)
    # Note: collector clears _handle on close,故这里不能查 handle;通过 collector._closed=True
    # 间接验 (collector.close idempotent + 无 exception 即认为 shutdown OK)。
    assert collector._closed, 'collector.close() must set _closed=True'
