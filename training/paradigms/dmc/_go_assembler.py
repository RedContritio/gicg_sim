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

Ingest 路径(``ingest`` / ``ingest_episode`` + per-episode buffer dataclass)拆在
``_go_assembler_ingest.py`` 的 ``_AssemblerIngestMixin``(file-budget cap,纯搬家);本模块
保留构造 / 组装(``_try_assemble``)/ drain / 诊断快照。
"""

from __future__ import annotations

import sys
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Optional

from training.paradigms.dmc.buffer import DmcTransition
from training.paradigms.dmc._decoder import _capture_obs_np
from training.paradigms.dmc._go_assembler_ingest import _AssemblerIngestMixin, _EpisodeBuf

# Stale-episode 阈值(秒)— 超过此时长未 ingest 新 transition 的 in-flight episode 视为
# orphan (actor 死亡 / conn reset 遗留)。 stats() 报告 n_stale_episodes 让 collector
# emit 进 backpressure metrics,production debug 直接 grep。 IPC Risk #5 (2026-05-28 audit)。
STALE_EPISODE_THRESHOLD_S = 60.0


@dataclass
class AssembledEpisode:
    """Output of assembler — DmcTransition[] + winner ready for DMCBuffer.push_episode。"""

    client_id: int
    episode_id: int
    transitions: list[DmcTransition]
    winner: int  # +1 = me_won, -1 = me_lost, 0 = draw/timeout


class DmcTransitionAssembler(_AssemblerIngestMixin):
    """Reassemble episodes from Go socket transitions。

    Network architecture params (``n_counter_slots / n_hooks / max_ops_per_hook /
    fields_per_op / max_actions``) 由 caller 在 ``__init__`` 提供 — 这些是 scenario-cfg
    确定的固定 shape,assembler 内部走 ``_capture_obs_np`` 等 helper 需要。

    Ingest 入口(``ingest`` / ``ingest_episode``)来自 ``_AssemblerIngestMixin``。
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
