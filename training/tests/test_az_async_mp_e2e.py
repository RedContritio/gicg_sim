"""AZ async mp e2e smoke (smoke_full marker, opt-in).

Real-spawn validation of the I31 #88 AZ mp-pool unification: spawn N actors via
:class:`~training.paradigms.az._async.AZAsyncCollector` → each child resolves the
AZ ``mp_factories`` builders + drives an ``AZSelfPlayRunner`` (AB14
``episode_runner_factory`` wrapping the existing ``play_self_game``, NOT the default
``EpisodeRunner``) through the shared ``core/actor`` runtime, routing every MCTS
eval through a per-actor ``InferenceClient`` to the parent ``InferenceServer``
(server owns the weights) → pushes an ``_AZRunnerOutput`` (carrying a
``SelfPlayResult``) back through the SHM ring → ``collect`` drains them.

Closes the long-missing AZ real-spawn e2e: ``test_az_async_collector.py`` is
mock-light (fake server/client, no real process) and its docstring promised a
"T7 smoke_full suite" that was never built. CFR/PPO have their async mp e2e; AZ
did not until this. Verifies the unified-pipeline AZ async path actually spawns
and tears down cleanly — the prerequisite for retiring the legacy AZ stack
(``train_az`` / ``run_async`` / ``inference_pool``) per 方向 C.

Marked ``smoke_full`` (not default-collected). Sandbox note: real mp spawn uses
``bind()`` / ``nice()`` the Mac Claude Code sandbox may block (memory
``project_pre_existing_sandbox_failures``); runs clean on CI / non-sandbox dev.
AZ Python-actor inference is mp.Pipe (not TCP), so no socket bind — same spawn
surface as the CFR e2e that runs clean here.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest


pytestmark = pytest.mark.smoke_full


def _build_az_async_cfg(num_actors: int = 2) -> object:
    """Load configs/az/smoke.toml then force pipeline.mode='async' + num_actors
    (mirrors the CFR e2e's _build_cfr_async_cfg)."""
    from training.core.config import load_cfg

    cfg_path = Path(__file__).resolve().parents[2] / 'configs' / 'az' / 'smoke.toml'
    cfg = load_cfg(str(cfg_path))
    cfg = replace(cfg, pipeline=replace(cfg.pipeline, mode='async', num_actors=num_actors))
    return cfg


def _fresh_actor_log_tracebacks(cfg: object, since_ts: float) -> list[str]:
    """``actor_<id>.log`` tails written this test (mtime >= since_ts) that contain
    a Python traceback — a child-side spawn failure (build_provider raising on a
    cold InferenceClient handoff, or build_az_selfplay_runner not wiring) lands here
    even though the parent never sees the child raise."""
    runtime = getattr(cfg, 'runtime', None)
    log_dir = Path(getattr(runtime, 'actor_log_dir', None) or 'artifacts/_actor_logs')
    if not log_dir.exists():
        return []
    hits: list[str] = []
    for lf in log_dir.glob('actor_*.log'):
        try:
            if lf.stat().st_mtime < since_ts:
                continue
            txt = lf.read_text(encoding='utf-8', errors='replace')
        except OSError:
            continue
        if 'Traceback (most recent call last)' in txt:
            hits.append(f'{lf.name}:\n{txt[-2000:]}')
    return hits


def test_az_async_collector_mp_spawn_and_clean_shutdown():
    """E2E smoke:真 spawn 2 actor 跑 AZ selfplay → drain ≥0 game(bounded grace)或
    干净收尾。 验证:
    - AZAsyncCollector.collect 触发 _bootstrap(InferenceServer 起 + push 初始权重 +
      N InferenceClient + 2-actor spawn via AB14 episode_runner_factory)不 crash
    - actor 子进程 build_provider 拿 inference_client + build_az_selfplay_runner →
      play_self_game 经 InferenceClient 路由 eval(成功判据 = non-crashing spawn +
      bounded shutdown;drain >0 是 bonus,MCTS selfplay 慢可能 0)
    - 输出 shape 与 serial AZSelfPlayCollector 一致(transitions==[] + az_trajectories
      list)
    - sync_weights bump _weights_version(server.push_weights)
    - state_dict 往返(resume contract)
    - close 顺序干净, bounded < 12s

    drain 0 且 actor_<id>.log 有 traceback → composed handoff bug → FAIL;
    drain 0 且 clean-log → tolerate(spawn-blocked sandbox / MCTS 慢未完成一局)。
    """
    from training.paradigms.az._async import AZAsyncCollector
    from training.paradigms.az.config import AZParadigmConfig
    from training.paradigms.az.paradigm import AZParadigm

    cfg = _build_az_async_cfg(num_actors=2)
    pcfg = AZParadigmConfig.from_dict(cfg.paradigm)
    network = AZParadigm().make_network(cfg)

    t_start = time.time()
    collector = None
    try:
        collector = AZAsyncCollector(cfg, pcfg, network, env_factory=None)

        # First collect bootstraps (server + 2-actor spawn). Bounded grace so the
        # MCTS selfplay actors have a chance to finish ≥1 game; tolerate 0.
        deadline = time.time() + 25.0
        total_pulled = 0
        trajs: list = []
        last_out = None
        while time.time() < deadline and total_pulled < 1:
            last_out = collector.collect(n_episodes=8, provider=None)
            total_pulled += last_out.runtime_metrics['n_pulled']
            trajs.extend(last_out.runtime_metrics['az_trajectories'])
            if total_pulled < 1:
                time.sleep(1.5)

        # Output shape parity with serial AZSelfPlayCollector.collect.
        assert last_out is not None
        assert last_out.transitions == []
        assert isinstance(last_out.runtime_metrics['az_trajectories'], list)

        # Real-spawn correctness — NOT just "non-crashing": a drained trajectory
        # MUST carry selfplay steps; 0-drained is tolerated ONLY without a child
        # traceback (MCTS selfplay slow / spawn-blocked sandbox).
        if total_pulled > 0:
            assert all(len(steps) > 0 for _gs, steps in trajs), (
                'drained AZ trajectories but some carry 0 steps — selfplay produced no moves'
            )
        else:
            tb = _fresh_actor_log_tracebacks(cfg, t_start)
            assert not tb, 'AZ actors drained 0 games AND logged a child traceback:\n' + '\n'.join(tb)

        # sync_weights bumps version (server.push_weights — AZ weights server-side).
        v0 = collector._weights_version
        assert collector.sync_weights(network) == v0 + 1
        assert collector._weights_version == v0 + 1

        # state_dict round-trip (resume contract).
        sd = collector.state_dict()
        assert sd['weights_version'] == v0 + 1
    finally:
        if collector is not None:
            t_close = time.time()
            collector.close()
            assert (time.time() - t_close) < 12.0, 'AZAsyncCollector.close hung (> 12s)'
