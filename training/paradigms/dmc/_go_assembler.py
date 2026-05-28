"""DmcTransitionAssembler — Go subprocess 产 transitions 重组成 DmcTransition + winner。

Pipeline (I29 redesign P3 post-2026-05-25):
- master 端 ``DMCGoSubprocessCollector.collect`` 周期 poll SHMRing trans channel,从
  ``try_pop_with_meta`` 拿 raw frame → ``decode_episode_batch`` → ``assembler.ingest_episode``
- assembler 按 ``(client_id, episode_id)`` buffer transitions
- 见 ``done=True`` 时 assemble:
  · 走 ``_capture_obs_np`` (reuse Python actor 同算法) 把 raw bytes 拼成 obs_dict
  · 终态 reward 作 episode winner 推算(+1=me_won, -1=opp_won, 0=draw)
  · ``DmcTransition[]`` + winner 移到 ``ready_episodes`` 队列
- ``DMCGoSubprocessCollector.collect`` 走 ``drain_ready()`` 拿 episodes,然后 push 到
  ``DMCBuffer.push_episode``。

边界:
- Assembler 不知 network — static_obs 直接从 first transition 提取 + 解码(reuse
  ``_encode_static_np``,纯 numpy 不 import torch);后续 transition NStatic=0 走
  hash cache lookup。
- thread-safe:F1 episode-batch path 下,master driver thread 单线程 ingest_episode →
  collect,不需 lock。 历史 per-trans path (pre-F1) listener thread + collector thread
  共享 state via lock,P3 redesign 后 listener thread 已删,但 ingest/drain_ready 仍保
  thread-safe (future-proof — 若加 callable sampler 在 driver thread 外 poll stats)。
- 失序保护:Go subprocess goroutine 单一 SHMRing push 串行化顺序,但 N actor 并发
  → step 顺序保证仅 per (client_id, episode_id);assembler 检测 step skip 报错。
"""

from __future__ import annotations

import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

# Stale-episode 阈值(秒)— 超过此时长未 ingest 新 transition 的 in-flight episode 视为
# orphan (actor 死亡 / conn reset 遗留)。 stats() 报告 n_stale_episodes 让 collector
# emit 进 backpressure metrics,production debug 直接 grep。 IPC Risk #5 (2026-05-28 audit)。
STALE_EPISODE_THRESHOLD_S = 60.0

from training.core.actor.transition_sink_wire import (
    DmcTransitionPayload,
    EpisodeBatch,
    Transition,
    decode_dmc_payload,
)
from training.core.perf import trace
from training.paradigms.dmc.buffer import DmcTransition
from training.paradigms.dmc._decoder import _capture_obs_np, _encode_static_np


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


@dataclass
class AssembledEpisode:
    """Output of assembler — DmcTransition[] + winner ready for DMCBuffer.push_episode。"""

    client_id: int
    episode_id: int
    transitions: list[DmcTransition]
    winner: int  # +1 = me_won, -1 = me_lost, 0 = draw/timeout


class DmcTransitionAssembler:
    """Reassemble episodes from Go socket transitions。

    Network architecture params (``n_counter_slots / n_hooks / max_ops_per_hook /
    fields_per_op / max_actions``) 由 caller 在 ``__init__`` 提供 — 这些是 scenario-cfg
    确定的固定 shape,assembler 内部走 ``_capture_obs_np`` 等 helper 需要。
    """

    def __init__(
        self,
        *,
        n_counter_slots: int,
        n_hooks: int,
        max_ops_per_hook: int,
        fields_per_op: int,
        max_actions: int,
        max_inflight_episodes: int = 1024,
    ) -> None:
        self.n_counter_slots = n_counter_slots
        self.n_hooks = n_hooks
        self.max_ops_per_hook = max_ops_per_hook
        self.fields_per_op = fields_per_op
        self.max_actions = max_actions
        # 在途 episode 上限 — 健康运行下 _buffers ≈ n_actors(每 actor 1 个在途
        # episode);超限说明有 orphaned episode(actor 死亡 / conn reset 遗留永不 done
        # 的 _EpisodeBuf)堆积。 超限驱逐最旧(最可能 orphaned)防无界泄漏(I29 T-RR.2)。
        self._max_inflight = int(max_inflight_episodes)

        self._lock = threading.Lock()
        # OrderedDict — 按插入序,在途上限超时 popitem(last=False) 驱逐最旧。
        self._buffers: 'OrderedDict[tuple[int, int], _EpisodeBuf]' = OrderedDict()
        self._ready: list[AssembledEpisode] = []
        # Diagnostic counters — `stats()` 暴露,collector log 'backpressure' kind 含,可观测
        # ingest vs drop pattern (cache miss / orphan / evict)。
        self._n_ingest_called: int = 0
        self._n_dropped_static_miss: int = 0
        self._n_assembled: int = 0
        self._n_evicted_inflight: int = 0
        # Static obs decoded numpy fields,keyed by 16-byte hash。 N actor 同 scenario 共享
        # 1 entry — 'fixed-scenario DMC 编 1 次' (mirror server-side shared_cache 设计)。
        # 有意不设上界:fixed-scenario 假设下恒 1 entry。 若未来 scenario / obs schema
        # 跨 run 变化致 hash 漂移,此 cache 会单调增长 —— 届时需配 LRU(目前 out of scope)。
        self._static_cache: dict[bytes, dict] = {}

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

    def _try_assemble(self, client_id: int, episode_id: int, buf: _EpisodeBuf) -> Optional[AssembledEpisode]:
        """Build DmcTransition[] + winner。 Returns None when static cache miss(scenario 第一 episode
        漏了 static — caller 上游应保证 first transition step 0 携带 static)。"""
        if buf.static_hash is None or buf.static_hash not in self._static_cache:
            print(
                f'[DmcAssembler] static cache miss client={client_id} ep={episode_id} hash={(buf.static_hash or b"").hex()[:12]} — dropping episode',
                file=sys.stderr,
                flush=True,
            )
            return None
        static_np = self._static_cache[buf.static_hash]

        # Determine winner from last transition's reward (set in terminalReward Go side
        # only on the done=True transition;non-terminal transitions have reward=0)
        last = buf.payloads[-1]
        if last.reward > 0.5:
            winner = 1
        elif last.reward < -0.5:
            winner = -1
        else:
            winner = 0

        transitions: list[DmcTransition] = []
        for dmc in buf.payloads:
            if dmc.n_legal == 0:
                # terminal marker(I29 T-RR.1)—— NLegal=0 无 obs,不产 DmcTransition。
                continue
            # refs/pay 必为 nlegal-sized(I29 P2 wire v3 起,Go encode 已 slice 到 nlegal)。
            # size 不符 = wire/encoder 不一致 —— fail-loud,不静默退化(I29 T-RR.6)。
            if dmc.refs.size != dmc.n_legal * 3 or dmc.pay.size != dmc.n_legal * 8:
                raise ValueError(
                    f'DMC transition refs/pay size mismatch client={client_id} ep={episode_id}: '
                    f'refs={dmc.refs.size} (want {dmc.n_legal * 3}=n_legal*3) '
                    f'pay={dmc.pay.size} (want {dmc.n_legal * 8}=n_legal*8) — wire v3 expects nlegal-sized'
                )
            refs_nlegal = dmc.refs.reshape(dmc.n_legal, 3)
            pay_nlegal = dmc.pay.reshape(dmc.n_legal, 8)
            obs_dict = _capture_obs_np(
                dyn_obs=dmc.dyn_obs,
                n_legal=dmc.n_legal,
                refs_nlegal=refs_nlegal,
                pay_nlegal=pay_nlegal,
                n_counter_slots=self.n_counter_slots,
                static_np=static_np,
            )
            if not obs_dict:
                continue
            transitions.append(
                DmcTransition(
                    obs_dict=obs_dict,
                    action_idx=dmc.chosen_action,
                    G=0.0,  # backfilled by DmcReplayBuffer.push_episode
                )
            )
        return AssembledEpisode(
            client_id=client_id,
            episode_id=episode_id,
            transitions=transitions,
            winner=winner,
        )

    def drain_ready(self) -> list[AssembledEpisode]:
        """Atomic drain of all ready episodes since last call。 thread-safe。"""
        with self._lock:
            out = list(self._ready)
            self._ready.clear()
        return out

    def n_pending(self) -> int:
        """Count of in-flight episodes(observed but not yet done=True)— diagnostic。"""
        with self._lock:
            return len(self._buffers)

    def n_ready(self) -> int:
        """Count of assembled episodes pending drain — diagnostic。"""
        with self._lock:
            return len(self._ready)

    def stats(self) -> dict[str, Any]:
        """One-shot snapshot of cache / buffer state — diagnostic for collector metrics。

        IPC Risk #5: n_stale_episodes 计 last_update_ts 比当前晚 STALE_EPISODE_THRESHOLD_S
        以上的 in-flight episode (默认 60s) — 这些 episode 长时间没 ingest 新 transition,
        疑似 actor crash 后遗留;persistent > 0 即 long-run train 静默丢 episode 信号。
        """
        now = time.monotonic()
        with self._lock:
            n_stale = sum(
                1
                for buf in self._buffers.values()
                if buf.last_update_ts > 0 and (now - buf.last_update_ts) > STALE_EPISODE_THRESHOLD_S
            )
            return {
                'n_pending_episodes': len(self._buffers),
                'n_ready_episodes': len(self._ready),
                'n_static_cache_entries': len(self._static_cache),
                'n_ingest_called': self._n_ingest_called,
                'n_dropped_static_miss': self._n_dropped_static_miss,
                'n_assembled': self._n_assembled,
                'n_evicted_inflight': self._n_evicted_inflight,
                'n_stale_episodes': n_stale,
            }
