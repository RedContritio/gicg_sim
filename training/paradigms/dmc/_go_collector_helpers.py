"""DMCGoSubprocessCollector 私有实现 — SHM frame 解码 + spawn bootstrap + Go backpressure 聚合。

从 ``go_subprocess_collector`` 拆出的三块内聚实现 (原模块超 300 行上限):

  * ``_strip_outer_length_and_decode`` — SHM ring slot 原始 frame 的 4-byte outer
    length prefix strip + wire decode。
  * ``_GoCollectorInternalMixin._bootstrap`` — 三件套 (InfServer + SHM ring + Go
    subprocess) atomic spawn。
  * ``_GoCollectorInternalMixin._aggregate_backpressure_metrics`` — per-actor
    Go-side backpressure snapshot 聚合。

三者都是 collection 状态机之外的内务 (raw bytes / 进程 spawn / stderr 统计),由
``DMCGoSubprocessCollector`` 继承取得 — 方法名 / 签名 / 语义与拆出前逐字一致,纯搬家。
``collect()`` / ``sync_weights()`` / ``close()`` 等 collector 协议面仍留在原模块。

本模块不 import ``go_subprocess_collector`` (单向依赖,无环)。
"""

from __future__ import annotations

from typing import Any

from training.core.actor.go_subprocess_pipeline import make_unique_shm_name, spawn_pipeline
from training.core.actor.transition_sink_wire import (
    EpisodeBatch as _EpisodeBatch,
    decode_episode_batch,
)


def _strip_outer_length_and_decode(raw_frame: bytes) -> _EpisodeBatch:
    """Strip 4-byte outer length prefix from SHM ring slot frame → decode_episode_batch。

    Go EncodeEpisodeBatch 输出 [u32 outer_len][EpisodeBatchHeader][per-tx records]。
    SHM path 直接搬运原 bytes 需 caller strip 4-byte prefix (TCP socket reader 框架已 strip
    长度前缀,SHM ring slot 原样含 prefix)。
    """
    import struct as _struct

    if len(raw_frame) < 4:
        raise ValueError(f'SHM frame too short {len(raw_frame)} byte for outer length prefix')
    (outer_len,) = _struct.unpack_from('<I', raw_frame, 0)
    body = raw_frame[4 : 4 + outer_len]
    if len(body) != outer_len:
        raise ValueError(f'SHM frame truncated: outer_len={outer_len} but body={len(body)}')
    return decode_episode_batch(body)


class _GoCollectorInternalMixin:
    """DMCGoSubprocessCollector 的内务实现 — 依赖 subclass 提供构造期设置的实例属性。

    依赖属性 (均由 ``DMCGoSubprocessCollector.__init__`` 设置):``network`` /
    ``paradigm_cfg_dict`` / ``n_actors`` / ``tuning`` / ``_max_actions`` / ``_device`` /
    ``_spawned`` / ``_handle``。
    """

    _handle: Any

    def _bootstrap(self) -> None:
        """Atomic spawn 三件套 (InfServer + SHM + Go subprocess) — 等同 cgo path 的
        _bootstrap,但 zero cgo lib + zero listener thread。 失败时由 spawn_pipeline 内部
        cleanup 已 spawn 的部分,这里只 propagate exception。
        """
        if self._spawned:
            return
        shm_name = make_unique_shm_name('p14_t')
        self._handle = spawn_pipeline(
            network=self.network,
            paradigm_name='dmc',
            paradigm_config=self.paradigm_cfg_dict,
            n_actors=self.n_actors,
            shm_ring_name=shm_name,
            inf_max_actions=self._max_actions,
            request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
            # W2-1: encoder path (was hard-imported at inference_server.py:164
            # pre-2026-05-28 — DMC paradigm now self-reports it like the decoder)。
            socket_payload_encoder_path='training.paradigms.dmc._socket_decoder.socket_request_to_pickled_payload',
            tuning=self.tuning,
            device=self._device,
        )
        self._spawned = True

    def _aggregate_backpressure_metrics(self) -> dict:
        """Aggregate per-actor Go-side backpressure stats (push_total / push_wait_ms /
        push_drops) 从 stderr parser 维护的 per-actor latest snapshot 取。 spawn 前或第一
        50-episode 报告前返空 — caller (pipeline.collect → state.after_collect → metrics_logger
        iter row) auto-skips 缺字段。"""
        if self._handle is None:
            return {}
        per_actor: dict = {}
        push_total_sum = 0
        push_wait_ms_sum = 0.0
        push_drops_sum = 0
        for go_proc in self._handle.go_procs:
            stats = go_proc.get_backpressure_stats()
            for actor_id, s in stats.items():
                per_actor[actor_id] = s
                push_total_sum += s.get('push_total', 0)
                push_wait_ms_sum += s.get('push_wait_ms', 0.0)
                push_drops_sum += s.get('push_drops', 0)
        if not per_actor:
            return {}
        return {
            'go_backpressure_push_total': push_total_sum,
            'go_backpressure_push_wait_ms_total': round(push_wait_ms_sum, 1),
            'go_backpressure_push_drops_total': push_drops_sum,
            'go_backpressure_actors_reported': len(per_actor),
            # avg push_wait per push (across all reporting actors) — direct backpressure 信号:
            # > 1 ms = train cycle 占 wall 让 actor 累计等 SHM slot;> 100 ms = 严重 backpressure
            # (train rate << collect rate)。
            'go_backpressure_push_wait_ms_avg': round(push_wait_ms_sum / max(1, push_total_sum), 3),
        }
