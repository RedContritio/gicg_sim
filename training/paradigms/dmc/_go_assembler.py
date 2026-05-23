"""DmcTransitionAssembler — Go actor-pool 产 transitions 重组成 DmcTransition + winner。

Pipeline:
- transition_sink_listener callback per transition → 调 ``assembler.ingest(t)``
- assembler 按 ``(client_id, episode_id)`` buffer transitions
- 见 ``done=True`` 时 assemble:
  · 走 ``_capture_obs_np`` (reuse Python actor 同算法) 把 raw bytes 拼成 obs_dict
  · 终态 reward 作 episode winner 推算(+1=me_won, -1=opp_won, 0=draw)
  · ``DmcTransition[]`` + winner 移到 ``ready_episodes`` 队列
- DMCGoActorCollector.collect 走 ``drain_ready()`` 拿 episodes,然后 push 到
  ``DMCBuffer.push_episode``。

边界:
- Assembler 不知 network — static_obs 直接从 first transition 提取 + 解码(reuse
  ``_encode_static_np``,纯 numpy 不 import torch);后续 transition NStatic=0 走
  hash cache lookup。
- thread-safe:transition sink callback 在 listener thread 调,collector.collect 在
  master thread 调 — ``ingest`` + ``drain_ready`` 共享 state via lock。
- 失序保护:Go side 单一 TransitionWriter mutex 串行化 push 顺序,但 N actor 并发
  → step 顺序保证仅 per (client_id, episode_id);assembler 检测 step skip 报错。
"""

from __future__ import annotations

import sys
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

import numpy as np

from training.core.actor.transition_sink_wire import (
    DmcTransitionPayload,
    Transition,
    decode_dmc_payload,
)
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
        # Static obs decoded numpy fields,keyed by 16-byte hash。 N actor 同 scenario 共享
        # 1 entry — 'fixed-scenario DMC 编 1 次' (mirror server-side shared_cache 设计)。
        # 有意不设上界:fixed-scenario 假设下恒 1 entry。 若未来 scenario / obs schema
        # 跨 run 变化致 hash 漂移,此 cache 会单调增长 —— 届时需配 LRU(目前 out of scope)。
        self._static_cache: dict[bytes, dict] = {}

    def ingest(self, t: Transition) -> None:
        """Append a transition to its episode buffer。 done=True 后 assemble + 入 ready。

        Thread-safe via ``self._lock``;sink callback in listener thread 直接调本方法。
        """
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
                episode = self._try_assemble(t.client_id, t.episode_id, buf)
                if episode is not None:
                    self._ready.append(episode)
                # 释放 buffer 内存
                del self._buffers[key]

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
        """One-shot snapshot of cache / buffer state — diagnostic for collector metrics。"""
        with self._lock:
            return {
                'n_pending_episodes': len(self._buffers),
                'n_ready_episodes': len(self._ready),
                'n_static_cache_entries': len(self._static_cache),
            }
