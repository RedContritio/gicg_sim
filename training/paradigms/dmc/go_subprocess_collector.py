"""DMCGoSubprocessCollector — I29 redesign subprocess-isolated DMC actor collector。

走 I29 redesign 架构:master 0 cgo lib + InferenceServer mp.Process + cmd/gicg_actor
OS subprocess + TransitionShmChannel SHM ring。 master polling try_pop_with_meta →
assembler.ingest_episode → collector return。

P3 ship (2026-05-25):cfg-driven dispatch entry — ``DMCParadigm._make_go_collector`` 在
``actor_backend='go'`` 时实例化本类。 替代 pre-redesign cgo path collector
(``DMCGoActorCollector`` + ctypes ``GoActorBackend``,后者已退役删除)。
详 docs/superpowers/specs/2026-05-25-i29-redesign-design.md §4。
"""

from __future__ import annotations

import time
from typing import Any, Optional

import torch

from training.core.actor.go_subprocess_pipeline import PipelineHandle
from training.core.actor.pipeline_tuning_cfg import PipelineTuningCfg
from training.core.protocols import CollectorOutput
from training.paradigms.dmc._go_assembler import DmcTransitionAssembler
from training.paradigms.dmc._go_collector_helpers import (
    _GoCollectorInternalMixin,
    _strip_outer_length_and_decode,
)


class DMCGoSubprocessCollector(_GoCollectorInternalMixin):
    """DMC Go-subprocess collector (I29 redesign P3 ship)。

    构造时 atomic spawn 三件套 (InfServer mp.Process + SHM ring + Go subprocess),
    ``collect()`` poll SHM ring 直到 ``n_episodes`` 个完整 episode 攒齐,返 ``CollectorOutput``。
    Network architecture params(``n_counter_slots`` 等)从 ``network.net.*`` attr 读
    (network 是 ``DMCNetwork`` 包 ``DmcAgent``,actor_critic = ``network.net``)。
    lifecycle:``__init__`` spawn → ``collect`` poll-ingest-assemble → ``close()``
    shutdown(Go SIGTERM → SHM unlink → InfServer)。 context manager / atexit 友好。
    """

    requires_network_in_collect = True

    def __init__(
        self,
        *,
        cfg: Any,
        network: torch.nn.Module,
        paradigm_cfg_dict: dict,
        n_actors: int = 1,
        # Tuning 字段全收纳 PipelineTuningCfg (C1 refactor 2026-05-26): 收纳 shm_capacity
        # / shm_slot_size / inf_max_batch / inf_batch_timeout_ms / ready_timeout_s /
        # io_timeout_ms / collect_deadline_s / poll_interval_s / device / go_gomaxprocs。
        # None → 全 default (production caller 用 — paradigm.py:_make_go_collector)。
        # Override via `PipelineTuningCfg(shm_capacity=16, device='cpu')` (test fixture)。
        tuning: Optional[PipelineTuningCfg] = None,
    ) -> None:
        self.cfg = cfg
        self.network = network
        self.paradigm_cfg_dict = paradigm_cfg_dict
        self.n_actors = int(n_actors)
        self.tuning = tuning if tuning is not None else PipelineTuningCfg()

        # Required — 无默认。 静默默认 30 会与网络 action 容量不一致 → 训练 gather OOB
        # (I29 T-R3 bug)。 caller(_make_go_collector / 测试)必须显式提供。
        self._max_actions = int(paradigm_cfg_dict['max_actions'])

        # Extract net architecture params for assembler — network 是 DMCNetwork wraps
        # DmcAgent actor_critic, .net attr 含 n_counter_slots / n_hooks / etc。 fallback
        # 到 network 自身 if 没 .net (test fixture 可能直接传 raw actor_critic)。
        actor_critic = network.net if hasattr(network, 'net') else network
        self.assembler = DmcTransitionAssembler(
            n_counter_slots=int(actor_critic.n_counter_slots),
            n_hooks=int(actor_critic.n_hooks),
            max_ops_per_hook=int(actor_critic.max_ops_per_hook),
            fields_per_op=int(actor_critic.fields_per_op),
            max_actions=self._max_actions,
            # 在途 episode 上限 — 健康运行 ≈ n_actors;32x 给 headroom (orphaned episode
            # 防泄漏 I29 T-RR.2)。
            max_inflight_episodes=max(256, 32 * self.n_actors),
        )

        # Resolve InfServer device — 默认 follow network parameters。
        device = self.tuning.device
        if device is None:
            device = str(next(network.parameters()).device)
        self._device = device

        self._weights_version = 0
        self._episode_seq = 0
        self._handle: Optional[PipelineHandle] = None
        self._closed = False
        # 调 _bootstrap 后置 True;close() 前重 collect 用。
        self._spawned = False
        # pipeline.run_pipeline 调 attach_metrics_logger 后 hold logger ref;collect 周期
        # log 'backpressure' kind 把 Go-side push wait / drop 累计落 metrics.jsonl。
        self._metrics_logger: Any = None

    def attach_metrics_logger(self, logger: Any) -> None:
        """Pipeline.run_pipeline calls 此 hook 给 collector logger ref (类比
        DMCMultiProcessCollector.attach_metrics_logger)。 collect 周期 log 'backpressure'
        kind 行,含 push_total / push_wait_ms_total / push_drops_total / push_wait_ms_avg /
        actors_reported,可观测 Go-side SHM ring backpressure (train-vs-collect 失衡信号)。"""
        self._metrics_logger = logger

    def collect(self, n_episodes: int, provider: Any = None) -> CollectorOutput:
        """Poll SHM ring → assembler.ingest_episode → drain_ready 攒够 n_episodes。

        ``provider`` 在 Go subprocess 路径不用 (actor 内部自带 InferenceClient TCP conn
        到 InfServer)— 签名兼容 CollectorOutput protocol。

        Deadline = ``self.collect_deadline_s`` 墙钟上限;到点返回已 ready 的 episode
        (可能 < n_episodes — caller 据 episode_stats 长度判别)。
        """
        del provider
        self._bootstrap()
        assert self._handle is not None

        target = max(1, int(n_episodes))
        deadline = time.monotonic() + self.tuning.collect_deadline_s
        _diag_pops_empty = 0
        _diag_pops_got = 0
        _diag_decode_err = 0
        # Loop: poll SHM → if frame received,decode & ingest → check ready count → repeat。
        # try_pop_with_meta 非阻塞 (None on empty);poll_interval_s sleep 防 busy spin。
        while self.assembler.n_ready() < target:
            if time.monotonic() >= deadline:
                break
            item = self._handle.trans_channel.try_pop_with_meta()
            if item is None:
                _diag_pops_empty += 1
                time.sleep(self.tuning.poll_interval_s)
                continue
            _diag_pops_got += 1
            _cid, _rid, raw_frame = item
            try:
                batch = _strip_outer_length_and_decode(raw_frame)
            except ValueError as exc:
                # Wire decode 失败 → 警告 + drop frame (assembler 不会 fail-loud)。
                _diag_decode_err += 1
                import sys

                print(
                    f'[DMCGoSubprocessCollector] SHM frame decode error cid={_cid} rid={_rid}: {exc}',
                    file=sys.stderr,
                    flush=True,
                )
                continue
            # 走 F1 fast path — episode-granularity ingest (single lock + assemble per ep)。
            self.assembler.ingest_episode(batch)

        ready = self.assembler.drain_ready()
        bp_metrics = self._aggregate_backpressure_metrics()
        # Augment with collector loop counters (per-collect-call snapshot)。
        # SHM ring race-aware probe (H3 2026-05-28):peek_count_and_full_at_head 区分
        # over-reserve race (count > 0 但 slot 全 EMPTY = bc6b1b8 修复留的瞬时窗口) vs
        # actor stall (count == 0 = 上游没 push)。 B-go-sustained-collection-deadlock
        # debug 直接 grep 'shm_ring_full_at_head' vs 'shm_ring_peek_count' 趋势判断。
        if self._handle is not None:
            _ring_count, _ring_full_at_head = self._handle.trans_channel.peek_count_and_full_at_head()
        else:
            _ring_count, _ring_full_at_head = -1, -1
        bp_metrics_with_loop = dict(bp_metrics) if bp_metrics else {}
        bp_metrics_with_loop.update(
            {
                'collect_pops_empty': _diag_pops_empty,
                'collect_pops_got': _diag_pops_got,
                'collect_decode_err': _diag_decode_err,
                'collect_n_ready_drained': len(ready),
                'shm_ring_peek_count': _ring_count,
                'shm_ring_full_at_head': _ring_full_at_head,
                'assembler_n_ingest': self.assembler.stats().get('n_ingest_called', 0),
                'assembler_n_assembled': self.assembler.stats().get('n_assembled', 0),
                'assembler_n_dropped_static_miss': self.assembler.stats().get('n_dropped_static_miss', 0),
                'assembler_n_evicted': self.assembler.stats().get('n_evicted_inflight', 0),
                'assembler_n_pending': self.assembler.stats().get('n_pending_episodes', 0),
                # IPC Risk #5: > 0 = 长 run 静默丢 episode 信号 (actor crash orphan 卡 LRU)。
                'assembler_n_stale': self.assembler.stats().get('n_stale_episodes', 0),
            }
        )
        # Emit 'backpressure' kind row to metrics.jsonl — 跨 collect call 保留每次 snapshot
        # 让 user 看 push_wait_ms_avg 随 train cycle 趋势 (steady-state < 1ms = train fast,
        # > 100ms = train 太慢 actors 累计等 ring slot,需 lower train_ratio 或加 capacity)。
        if self._metrics_logger is not None:
            self._metrics_logger.log('backpressure', bp_metrics_with_loop)
        if not ready:
            return CollectorOutput(
                transitions=[],
                episode_stats=[],
                runtime_metrics={'n_dmc_episodes': 0},
            )

        episodes_for_buffer: list[tuple[list, float]] = []
        episode_stats: list[dict] = []
        n_trans_total = 0
        for ep in ready:
            self._episode_seq += 1
            G = float(ep.winner)
            if ep.transitions:
                episodes_for_buffer.append((ep.transitions, G))
            n_trans_total += len(ep.transitions)
            episode_stats.append(
                {
                    'ep_idx': self._episode_seq,
                    'n_transitions': len(ep.transitions),
                    'winner': ep.winner,
                    'G': G,
                    'source': 'go_subprocess',
                    'client_id': ep.client_id,
                }
            )

        return CollectorOutput(
            transitions=[],
            episode_stats=episode_stats,
            runtime_metrics={
                'n_dmc_episodes': len(ready),
                'n_dmc_transitions': n_trans_total,
                'dmc_episodes': episodes_for_buffer,
                'assembler_stats': self.assembler.stats(),
            },
            n_units=n_trans_total,
        )

    def sync_weights(self, network: Any) -> int:
        """Publish learner weights to InfServer (mp.Queue 'weights' path)。

        InfServer 的 network 是 ``DMCInferenceNet(actor_critic)`` — spawn_pipeline caller
        passes 已 wrap 的 network 进来 (test fixture / production wrap)。 这里推
        ``actor_critic.state_dict()`` 加 ``net.`` 前缀,与 InfServer 端
        ``DMCInferenceNet.add_module('net', ...)`` 的 key namespace 对齐。
        """
        self._weights_version += 1
        actor_critic = network.net if hasattr(network, 'net') else network
        sd_cpu = {'net.' + k: v.detach().cpu() for k, v in actor_critic.state_dict().items()}
        if self._handle is not None and self._handle.server is not None:
            self._handle.server.update_network(sd_cpu)
        return self._weights_version

    def close(self) -> None:
        """Shutdown 顺序: Go subprocess SIGTERM → SHM unlink → InfServer stop。

        PipelineHandle.shutdown() 内部已封顺序 + try/except 隔离单失败,这里只调一次幂等
        (close 后 _spawned=False,重 close 直接 no-op)。
        """
        if self._closed:
            return
        if self._handle is not None:
            try:
                self._handle.shutdown(go_timeout_s=10.0, server_timeout_s=5.0)
            finally:
                self._handle = None
        self._spawned = False
        self._closed = True

    def __enter__(self) -> 'DMCGoSubprocessCollector':
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        # atexit-friendly best effort — interpreter shutdown 时 stderr 已 closed 不打日志。
        try:
            self.close()
        except Exception:
            pass

    def state_dict(self) -> dict:
        return {'episode_seq': self._episode_seq, 'weights_version': self._weights_version}

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._weights_version = sd.get('weights_version', 0)
