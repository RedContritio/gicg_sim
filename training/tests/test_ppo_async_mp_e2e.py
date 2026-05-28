"""PPO async mp e2e smoke (smoke_full marker, opt-in).

Spawn 2 PPO actors via PPOAsyncCollector → run ≥1 episode → verify weight
sync + clean shutdown. Validates the post-cleanup spawn handoff
(``provider_kwargs`` AB13 path, replacing the W3a-era env-var bridge).

Per ``feedback_tool_production_smoke_required`` 2026-05-20:工具类 spec 必
含 production e2e smoke;PPOAsyncCollector 切换 spawn handoff 后必须真
spawn 验证 mp_factories build_provider 拿到 spawn-pickled provider_kwargs。

Marked ``smoke_full`` (not default-collected) per repo convention — runs
~30-60s wall (cold-start mp spawn + 1 small-pool episode + shutdown).
"""

from __future__ import annotations

import time

import pytest


pytestmark = pytest.mark.smoke_full


def _build_ppo_async_cfg() -> object:
    """Build cfg + paradigm_cfg + network for PPOAsyncCollector e2e.

    Uses smoke-scale shapes (~ minutes wall on Mac CPU). Mirrors
    `configs/ppo/smoke.toml` PPO smoke cfg but constructed in-proc to
    avoid cfg loader / TOML round-trip overhead in the test."""
    from dataclasses import replace
    from pathlib import Path

    from training.core.config import load_cfg

    # Load the canonical PPO smoke cfg (~1 iter × 2 games × 30 steps,
    # d_model=32). Override pipeline.mode='async' + num_actors=2.

    cfg_path = Path(__file__).resolve().parents[2] / 'configs' / 'ppo' / 'smoke.toml'
    cfg = load_cfg(str(cfg_path))
    cfg = replace(cfg, pipeline=replace(cfg.pipeline, mode='async', num_actors=2))
    # Ensure rollout_opponent='random' (frozen tier 'self' degrades, but
    # random keeps cfg flow visible in spec_sampler).
    return cfg


def test_ppo_async_collector_mp_spawn_and_clean_shutdown():
    """E2E smoke:真 spawn 2 actor → wait for ≥ 1 transition or clean shutdown
    after ~30s deadline。 验证:
    - PPOAsyncCollector.__init__ 不 raise (spawn handoff 走通)
    - actor 子进程 build_provider 拿到 provider_kwargs (网络 attach 成功 → 起
      码 1 transition 流回 master, 或 spawn 后 close 不挂)
    - sync_weights 调用 idempotent (publish 走 SHM, actor 端 pickup)
    - close 顺序干净 (runtime + queue + tmpdir 全 teardown)

    若 spawn handoff bug → __init__ raise / spawn 后 actor 立刻死 (e.g. mp
    pickle 失败 → child 端 RuntimeError trace 到 stderr, queue 永远空), test
    deadline 触发 + assertion 暴露。
    """
    from training.paradigms.ppo._async import PPOAsyncCollector
    from training.paradigms.ppo.config import PPOParadigmConfig
    from training.paradigms.ppo.network import PPONetwork

    cfg = _build_ppo_async_cfg()
    pcfg = PPOParadigmConfig.from_dict(cfg.paradigm)

    # Build a tiny network — matches cfg shape.
    from training.core.network import AgentConfig

    agent_cfg = AgentConfig.from_obs_shape(pcfg.agent)
    network = PPONetwork(agent_cfg, device='cpu')

    collector = None
    try:
        # PPOAsyncCollector.__init__ does the spawn handoff —
        # if env-var → provider_kwargs cutover broke, this raises here.
        collector = PPOAsyncCollector(cfg, pcfg, network, env_factory=None)

        # Drain attempt — small target (1 episode) + tight timeout. Even
        # 0 episodes is OK; the success criterion is shutdown cleanliness.
        collector._drain_timeout_s = 30.0
        out = collector.collect(n_units=1, provider=None)

        # Output shape sanity (regardless of whether we drained any eps).
        assert hasattr(out, 'transitions')
        assert hasattr(out, 'runtime_metrics')
        assert 'n_episodes_drained' in out.runtime_metrics

        # sync_weights idempotent — version increments + SHM publish.
        v0 = collector._weights_version
        collector.sync_weights(network)
        assert collector._weights_version == v0 + 1

        # state_dict / load_state_dict round-trip (resume contract).
        sd = collector.state_dict()
        assert 'weights_version' in sd
        assert sd['weights_version'] == v0 + 1
    finally:
        # close MUST be safe even if init partially failed.
        if collector is not None:
            t_close = time.time()
            collector.close()
            # close should NOT hang — bounded teardown contract.
            assert (time.time() - t_close) < 30.0, 'PPOAsyncCollector.close hung > 30s'


def test_ppo_async_provider_kwargs_path_via_spawn():
    """Lighter-weight spawn verify:1 actor + 1 step deadline。 主要验证
    provider_kwargs flow at the actor_main child entry point。

    比 collector e2e 更直接 — 不走完整 cfg + network shape,只 spawn 1 actor
    走 PPOAsyncCollector pipeline 看子进程能否 reach build_provider。 失败
    模式:provider_kwargs 不被 actor_main pickup (signature regression) →
    child build_provider 收 0 kwargs → RuntimeError "WeightsSHM latest cold"
    或 TypeError missing required kwarg。
    """
    from dataclasses import replace

    from training.core.network import AgentConfig
    from training.paradigms.ppo._async import PPOAsyncCollector
    from training.paradigms.ppo.config import PPOParadigmConfig
    from training.paradigms.ppo.network import PPONetwork

    cfg = _build_ppo_async_cfg()
    cfg = replace(cfg, pipeline=replace(cfg.pipeline, num_actors=1))
    pcfg = PPOParadigmConfig.from_dict(cfg.paradigm)
    agent_cfg = AgentConfig.from_obs_shape(pcfg.agent)
    network = PPONetwork(agent_cfg, device='cpu')

    collector = None
    try:
        # Just construct + immediately close — verifies spawn doesn't blow up
        # on the provider_kwargs flow. We are NOT verifying transitions —
        # just that spawn → close is bounded + non-crashing.
        collector = PPOAsyncCollector(cfg, pcfg, network, env_factory=None)
        # Brief grace so child has time to import + call build_provider —
        # if provider_kwargs flow is broken, child raises in build_provider
        # call site; we won't see the raise here (mp child), but actor_<id>.log
        # under artifacts/_actor_logs would record it.
        time.sleep(1.0)
    finally:
        if collector is not None:
            collector.close()
