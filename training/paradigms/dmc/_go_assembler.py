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

import threading
from collections import defaultdict
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
    ) -> None:
        self.n_counter_slots = n_counter_slots
        self.n_hooks = n_hooks
        self.max_ops_per_hook = max_ops_per_hook
        self.fields_per_op = fields_per_op
        self.max_actions = max_actions

        self._lock = threading.Lock()
        self._buffers: dict[tuple[int, int], _EpisodeBuf] = defaultdict(_EpisodeBuf)
        self._ready: list[AssembledEpisode] = []
        # Static obs decoded numpy fields,keyed by 16-byte hash。 N actor 同 scenario 共享
        # 1 entry — 'fixed-scenario DMC 编 1 次' (mirror server-side shared_cache 设计)。
        self._static_cache: dict[bytes, dict] = {}

    def ingest(self, t: Transition) -> None:
        """Append a transition to its episode buffer。 done=True 后 assemble + 入 ready。

        Thread-safe via ``self._lock``;sink callback in listener thread 直接调本方法。
        """
        try:
            dmc = decode_dmc_payload(t.payload)
        except ValueError as exc:
            # Wire 解码失败 → 报错但不 crash assembler — drop this transition
            import sys

            print(f'[DmcAssembler] decode error client={t.client_id} ep={t.episode_id} step={t.step}: {exc}',
                  file=sys.stderr, flush=True)
            return

        key = (t.client_id, t.episode_id)
        with self._lock:
            buf = self._buffers[key]
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
            import sys

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
            refs_2d = dmc.refs.reshape(self.max_actions, 3) if dmc.refs.size == self.max_actions * 3 else dmc.refs
            pay_2d = dmc.pay.reshape(self.max_actions, 8) if dmc.pay.size == self.max_actions * 8 else dmc.pay
            obs_dict = _capture_obs_np(
                dyn_obs=dmc.dyn_obs,
                n_legal=dmc.n_legal,
                refs_padded=refs_2d,
                pay_padded=pay_2d,
                max_actions=self.max_actions,
                n_counter_slots=self.n_counter_slots,
                static_np=static_np,
            )
            if not obs_dict:
                # n_legal=0 case — skip(matches Python flow)
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
