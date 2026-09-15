"""DMC assembler ingest paths — raw transition / episode-batch → episode buffers。

Split out of ``_go_assembler.py`` for the file-budget cap. Pure relocation:
both method bodies are byte-identical to their previous home on
``DmcTransitionAssembler`` (only the class they are defined on changed), and
the module imports nothing from ``_go_assembler.py`` (no cycle)。
:class:`DmcTransitionAssembler` mixes this in and keeps ``__init__`` (buffer +
cache state), ``_try_assemble``, ``drain_ready`` and the ``stats()`` snapshot。

Two ingest entry points, both thread-safe via the owner's ``self._lock``:

- :meth:`_AssemblerIngestMixin.ingest` — per-transition (Go socket push path)。
- :meth:`_AssemblerIngestMixin.ingest_episode` — F1 episode-granularity fast
  path (Go ``PushBatch`` → single lock + single ``_try_assemble`` per episode)。

Owner-provided state consumed here: ``_lock`` / ``_buffers`` / ``_ready`` /
``_max_inflight`` / ``_static_cache`` / ``n_counter_slots`` / ``n_hooks`` /
``max_ops_per_hook`` / ``fields_per_op`` / the diagnostic counters /
``_try_assemble``。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from training.core.actor.dmc_transition_payload_wire import (
    DmcTransitionPayload,
    decode_dmc_payload,
)
from training.core.actor.transition_sink_wire import (
    EpisodeBatch,
    Transition,
)
from training.core.perf import trace
from training.paradigms.dmc._decoder import _encode_static_np


@dataclass
class _EpisodeBuf:
    """Per-(client_id, episode_id) accumulator state。"""

    payloads: list[DmcTransitionPayload] = field(default_factory=list)
    done: bool = False
    # 收第一条 transition 时已知 static_hash;cache 中可能已有(scenario shared);若 NStatic>0
    # 就 trigger 解码 + 入 cache。
    static_hash: Optional[bytes] = None
    # IPC Risk #5 (2026-05-28):monotonic 时间戳追踪 episode 活跃度。 created_ts 用于 eviction
    # log 报 age (orphan 多久卡在 LRU),last_update_ts 用于 stats() n_stale_episodes
    # 检测 (超 STALE_EPISODE_THRESHOLD_S 没 ingest 新 trans = 疑似 actor crash)。 0.0 默认
    # 仅 dataclass init 前用,ingest 内立即覆盖。
    created_ts: float = 0.0
    last_update_ts: float = 0.0


class _AssemblerIngestMixin:
    def ingest(self, t: Transition) -> None:
        """Append a transition to its episode buffer。 done=True 后 assemble + 入 ready。

        Thread-safe via ``self._lock``;sink callback in listener thread 直接调本方法。
        """
        with trace.span('assembler.decode_payload'):
            try:
                dmc = decode_dmc_payload(t.payload)
            except ValueError as exc:
                # Wire 解码失败 → 报错但不 crash assembler — drop this transition
                print(
                    f'[DmcAssembler] decode error client={t.client_id} ep={t.episode_id} step={t.step}: {exc}',
                    file=sys.stderr,
                    flush=True,
                )
                return

        key = (t.client_id, t.episode_id)
        with self._lock:
            with trace.span('assembler.append_buffer'):
                buf = self._buffers.get(key)
                if buf is None:
                    # 新 episode key — 在途上限检查,超限先驱逐「最久未活跃」episode。
                    # _buffers 是 LRU OrderedDict:活跃 episode 每收一条 transition 即
                    # move_to_end(见下 else 分支),故 popitem(last=False) 取的是最久没收到
                    # transition 的 —— 只要存在 orphan(actor 死亡 / conn reset 后永不再
                    # push),它的活跃度必低于任何健康 episode → 被优先驱逐,健康长 episode
                    # (GICG 单局可数百 step)不会被误杀。
                    if len(self._buffers) >= self._max_inflight:
                        old_key, _old = self._buffers.popitem(last=False)
                        print(
                            f'[DmcAssembler] inflight cap {self._max_inflight} reached — '
                            f'evicting least-recently-active in-flight episode '
                            f'client={old_key[0]} ep={old_key[1]} (likely orphaned)',
                            file=sys.stderr,
                            flush=True,
                        )
                    buf = _EpisodeBuf()
                    self._buffers[key] = buf
                else:
                    # 活跃 episode 收到新 transition → 移到 LRU 尾,使其不被误驱逐。
                    self._buffers.move_to_end(key)
                if buf.static_hash is None:
                    buf.static_hash = dmc.static_hash
                # static_obs cache populate (only first transition per episode carries it)
                if len(dmc.static) > 0 and dmc.static_hash not in self._static_cache:
                    self._static_cache[dmc.static_hash] = _encode_static_np(
                        dmc.static,
                        n_counter_slots=self.n_counter_slots,
                        n_hooks=self.n_hooks,
                        max_ops_per_hook=self.max_ops_per_hook,
                        fields_per_op=self.fields_per_op,
                    )
                buf.payloads.append(dmc)
                buf.done = t.done

            if buf.done:
                with trace.span('assembler.try_assemble'):
                    episode = self._try_assemble(t.client_id, t.episode_id, buf)
                if episode is not None:
                    self._ready.append(episode)
                # 释放 buffer 内存
                del self._buffers[key]

    def ingest_episode(self, batch: EpisodeBatch) -> None:
        """F1 fast path: Go PushBatch → single lock + single _try_assemble per episode。
        GIL overhead O(N/ep) → O(1/ep)。 Thread-safe。
        """
        with trace.span('assembler.ingest_episode'):
            decoded_list: list[DmcTransitionPayload] = []
            static_from_batch: Optional[DmcTransitionPayload] = None
            any_done = False
            for tx in batch.transitions:
                if tx.done:
                    any_done = True
                with trace.span('assembler.decode_payload'):
                    try:
                        dmc = decode_dmc_payload(tx.payload)
                    except ValueError as exc:
                        print(
                            f'[DmcAssembler] ingest_episode decode error client={batch.client_id} ep={batch.episode_id}: {exc}',
                            file=sys.stderr,
                            flush=True,
                        )
                        return
                decoded_list.append(dmc)
                if static_from_batch is None and len(dmc.static) > 0:
                    static_from_batch = dmc
            if not decoded_list:
                return
            key = (batch.client_id, batch.episode_id)
            with self._lock:
                self._n_ingest_called += 1
                now = time.monotonic()
                with trace.span('assembler.append_buffer'):
                    if key in self._buffers:
                        del self._buffers[key]
                    if len(self._buffers) >= self._max_inflight:
                        old_key, old_buf = self._buffers.popitem(last=False)
                        self._n_evicted_inflight += 1
                        # IPC Risk #5: 报 age 让 debug 看 orphan 卡多久 (actor crash 时长信号)。
                        age_s = now - old_buf.created_ts if old_buf.created_ts > 0 else -1.0
                        print(
                            f'[DmcAssembler] inflight cap {self._max_inflight} reached — '
                            f'evicting client={old_key[0]} ep={old_key[1]} age={age_s:.1f}s '
                            f'(likely orphaned, actor crash suspected)',
                            file=sys.stderr,
                            flush=True,
                        )
                    buf = _EpisodeBuf()
                    buf.payloads = decoded_list
                    buf.done = any_done
                    buf.created_ts = now
                    buf.last_update_ts = now
                    if decoded_list:
                        buf.static_hash = decoded_list[0].static_hash
                    if static_from_batch is not None and static_from_batch.static_hash not in self._static_cache:
                        self._static_cache[static_from_batch.static_hash] = _encode_static_np(
                            static_from_batch.static,
                            n_counter_slots=self.n_counter_slots,
                            n_hooks=self.n_hooks,
                            max_ops_per_hook=self.max_ops_per_hook,
                            fields_per_op=self.fields_per_op,
                        )
                if buf.done:
                    with trace.span('assembler.try_assemble'):
                        episode = self._try_assemble(batch.client_id, batch.episode_id, buf)
                    if episode is not None:
                        self._ready.append(episode)
                        self._n_assembled += 1
                    else:
                        self._n_dropped_static_miss += 1
                else:
                    self._buffers[key] = buf
