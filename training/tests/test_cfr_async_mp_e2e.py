"""CFR async mp e2e smoke (smoke_full marker, opt-in).

Real-spawn validation of the I31 #88 CFR mp-pool unification: spawn N actors
via :class:`~training.paradigms.cfr._async.CFRAsyncCollector` → each child
resolves the CFR ``mp_factories`` builders + drives a ``CFRTraversalRunner``
(AB14 ``episode_runner_factory``, NOT the default ``EpisodeRunner``) through
the shared ``core/actor`` runtime → pushes a ``_CFRRunnerOutput`` (carrying a
``CFRGameBatch``) back through the IPCQueue → ``collect`` drains them.

Validates the composed spawn handoff that the unit suite
(``test_cfr_async_collector.py``) cannot reach because it fakes the Runtime:
BOTH the AB13 ``provider_kwargs`` (WeightsSHM 2-slot info + 2-net blueprint
tempfile) AND the AB14 ``episode_runner_factory_path`` (traversal runner) must
flow across the spawn boundary, or the child raises in ``build_provider`` /
``build_cfr_traversal_runner`` and the queue stays empty.

Per ``feedback_tool_production_smoke_required`` 2026-05-20:工具类 / mp glue 必
含 production e2e smoke;CFRAsyncCollector 的 2-slot SHM + composed AB13/AB14
handoff 必须真 spawn 验证。

Marked ``smoke_full`` (not default-collected) per repo convention — runs cold
mp spawn + a few small-pool CFR traversals + shutdown (~minutes wall on Mac
CPU). Sandbox note: the Mac Claude Code sandbox may block ``bind()`` / ``nice()``
syscalls used by real mp spawn (memory
``project_pre_existing_sandbox_failures_2026_05_17``); these tests run clean
on CI / Windows / non-sandbox dev terminals.
"""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

import pytest


pytestmark = pytest.mark.smoke_full


def _build_cfr_async_cfg(num_actors: int = 2) -> object:
    """Build cfg from configs/cfr/smoke.toml then force pipeline.mode='async'
    + num_actors. Mirrors the PPO e2e's _build_ppo_async_cfg shape (load
    canonical smoke cfg + dataclass-replace the pipeline block)."""
    from training.core.config import load_cfg

    cfg_path = Path(__file__).resolve().parents[2] / 'configs' / 'cfr' / 'smoke.toml'
    cfg = load_cfg(str(cfg_path))
    cfg = replace(cfg, pipeline=replace(cfg.pipeline, mode='async', num_actors=num_actors))
    return cfg


def _fresh_actor_log_tracebacks(cfg: object, since_ts: float) -> list[str]:
    """Return ``actor_<id>.log`` tail excerpts that contain a Python traceback
    and were written during this test (mtime >= ``since_ts``).

    mp child stderr is teed to these files (``setup_actor_file_logging``), so a
    child-side spawn failure — ``build_provider`` raising on a cold SHM slot /
    2-net blueprint mismatch, or ``build_cfr_traversal_runner`` not wiring — lands
    here even though the parent never sees the child raise. The mtime filter
    avoids false positives from a prior test's actor logs in the shared dir."""
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


def test_cfr_async_collector_mp_spawn_and_clean_shutdown():
    """E2E smoke:真 spawn 2 actor 跑 CFR 树遍历 → drain ≤ 4 traversal 或在
    deadline 内干净收尾。 验证:
    - CFRAsyncCollector.__init__ 不 raise (2-slot SHM publish + 2-net blueprint
      + composed AB13 provider_kwargs / AB14 episode_runner_factory handoff 走通)
    - actor 子进程 build_provider 拿到 weights_shm_info + network_blueprint_path
      并 build_cfr_traversal_runner → 起码 0..N traversal 流回 master (even 0 是
      OK — 成功判据是 non-crashing spawn + bounded shutdown)
    - 输出 shape 与 serial CFRTraversalCollector 一致 (transitions==[] +
      runtime_metrics['cfr_batches'] list + n_drained/target_traversals keys)
    - sync_weights bump _weights_version (republish 两 slot)
    - state_dict 往返 (resume contract)
    - close 顺序干净, bounded < 30s

    若 composed handoff bug (provider_kwargs 漏 / episode_runner_factory 没透传)
    → child build_provider/runner raise (actor_<id>.log 记录) → queue 永空 →
    deadline 触发 short-drain, close 仍 bounded。
    """
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.config import CFRParadigmConfig
    from training.paradigms.cfr.paradigm import CFRParadigm

    cfg = _build_cfr_async_cfg(num_actors=2)
    pcfg = CFRParadigmConfig.from_dict(cfg.paradigm)
    # make_network is the canonical net builder (heads = avg_policy + 2 advantage).
    network = CFRParadigm().make_network(cfg)

    t_start = time.time()
    collector = None
    try:
        # __init__ does the 2-slot SHM publish + blueprint dump + spawn —
        # if the composed AB13/AB14 handoff broke, this raises here.
        collector = CFRAsyncCollector(cfg, pcfg, network, env_factory=None)

        collector._drain_timeout_s = 30.0
        out = collector.collect(n_units=4, provider=None)

        # Output shape parity with serial CFRTraversalCollector.collect.
        assert out.transitions == []
        assert isinstance(out.runtime_metrics['cfr_batches'], list)
        assert out.runtime_metrics['target_traversals'] == 4

        # Real-spawn correctness — NOT just "non-crashing". A silently broken
        # traversal path (cold SHM / blueprint mismatch / unwired runner) drains
        # 0 and logs a child traceback. So: if anything drained, assert the
        # batches actually carry samples; if nothing drained, FAIL when a child
        # traceback is present (real bug), tolerate only a clean-log 0 (a spawn-
        # blocked sandbox — no traceback — per the module docstring's note).
        n_drained = out.runtime_metrics['n_drained']
        if n_drained > 0:
            batches = out.runtime_metrics['cfr_batches']
            assert len(batches) == n_drained
            assert any(sum(b.n_samples()) > 0 for b in batches), (
                'drained CFRGameBatches but every one is empty — traversal produced no samples'
            )
        else:
            tb = _fresh_actor_log_tracebacks(cfg, t_start)
            assert not tb, 'CFR actors drained 0 traversals AND logged a child traceback:\n' + '\n'.join(tb)

        # sync_weights bumps version (republishes both advantage slots).
        v0 = collector._weights_version
        collector.sync_weights(network)
        assert collector._weights_version == v0 + 1

        # state_dict / load_state_dict round-trip (resume contract).
        sd = collector.state_dict()
        assert sd['weights_version'] == v0 + 1
        collector._weights_version = 0
        collector.load_state_dict(sd)
        assert collector._weights_version == v0 + 1
    finally:
        # close MUST be safe + bounded even if init partially failed. The infra
        # fix makes close non-blocking (cancel_join_thread, no join), so 2 actors
        # tear down in << 12s (Runtime.terminate is ~4s/actor worst case).
        if collector is not None:
            t_close = time.time()
            collector.close()
            assert (time.time() - t_close) < 12.0, 'CFRAsyncCollector.close hung (> 12s)'


def test_cfr_async_traversal_runner_via_spawn():
    """Lighter-weight spawn verify:1 actor 构造 + 1s grace + close。 主要验证
    spawn 抵达子进程的 build_provider + build_cfr_traversal_runner 而不 crash。

    比 collector e2e 更直接 — 失败模式是 broken provider_kwargs /
    episode_runner_factory handoff → child 在 build_provider (cold SHM slot /
    非 2-net blueprint) 或 build_cfr_traversal_runner raise → queue 永空。
    我们在 master 看不到 child raise (mp child),但 actor_<id>.log under
    artifacts/_actor_logs 会记录;此处只验证 spawn → close bounded + non-crashing。
    """
    from training.paradigms.cfr._async import CFRAsyncCollector
    from training.paradigms.cfr.config import CFRParadigmConfig
    from training.paradigms.cfr.paradigm import CFRParadigm

    cfg = _build_cfr_async_cfg(num_actors=1)
    pcfg = CFRParadigmConfig.from_dict(cfg.paradigm)
    network = CFRParadigm().make_network(cfg)

    collector = None
    try:
        collector = CFRAsyncCollector(cfg, pcfg, network, env_factory=None)
        # Brief grace so the child has time to import + reach build_provider +
        # build_cfr_traversal_runner — a broken handoff raises there (logged to
        # actor_<id>.log), not in this parent.
        time.sleep(1.0)
    finally:
        if collector is not None:
            t_close = time.time()
            collector.close()
            assert (time.time() - t_close) < 12.0, 'CFRAsyncCollector.close hung (> 12s)'
