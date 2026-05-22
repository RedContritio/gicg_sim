"""DMCGoActorCollector — Go-native actor pool collector for DMC paradigm。

Wire DMC Go-native actor pool + Python InferenceServer with embedded socket listener
+ Python transition sink listener + DmcTransitionAssembler 全栈,以 ``Collector`` protocol
暴露给 driver。

Architecture(对应 design.md):

    ┌─ Python master ────────────────────────────────────────────────────┐
    │                                                                    │
    │  InferenceServer (mp.Process)                                      │
    │   ├─ socket listener thread (Go → forward → response)              │
    │   └─ embedded forward_callback走 decode_dmc_request                │
    │                                                                    │
    │  Transition sink listener (in master thread) → assembler.ingest    │
    │                                                                    │
    │  GoActorBackend (ctypes → libgicg_actor.dylib goroutine pool)      │
    │                                                                    │
    └────────────────────────────────────────────────────────────────────┘

边界 vs DMCMultiProcessCollector:
- Mp 路径 spawn N Python actor process(分布 CPU)。
- Go 路径 spawn N Go goroutine 在 1 个 Go runtime 进程内(独立 lib,libgicg_actor)。
- Inference forward 在 Mp 路径走 mp.Queue,Go 路径走 socket(InfServer 同 process 内
  listener thread)。
- transition push:Mp 路径走 SHMRing,Go 路径走 socket(TCP localhost + assembler 重组)。
- DMCBuffer.push_episode 走完全一致 — Go path 拿到 DmcTransition[] + winner G,与
  Python actor path 入 buffer 路径无别。

P1.4 ship 阶段 spec(对照 DMCMultiProcessCollector):
- collect:assembler.drain_ready → DmcBuffer.push_episode(via paradigm strategy)→
  CollectorOutput with episode_stats + n_units (= n_transitions)
- sync_weights:走 InferenceServer.update_network(mp.Queue path)
- close:graceful shutdown(GoActorBackend.stop + InfServer.stop + listener stop)
"""

from __future__ import annotations

import socket
import threading
from typing import Any, Optional

import torch

from training.core.actor.go_backend import GoActorBackend
from training.core.actor.inference_server import InferenceServer
from training.core.actor.transition_sink_listener import (
    start_listener_in_thread as start_trans_listener,
    stop_listener as stop_trans_listener,
)
from training.core.actor.transition_sink_wire import Transition as _Transition
from training.core.protocols import CollectorOutput
from training.paradigms.dmc._go_assembler import AssembledEpisode, DmcTransitionAssembler


def _free_port() -> int:
    """获取一个未占用 localhost 端口 — bind 0 + read assigned。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


class DMCGoActorCollector:
    """DMC Go-native actor pool collector。

    构造时给定 network + scenario / paradigm_cfg,start_pool 起整栈。 collect 走
    assembler.drain_ready,返 CollectorOutput + 把 raw AssembledEpisode 入
    ``self.last_episodes`` 让 paradigm strategy / buffer 入栈。

    Network architecture params(``n_counter_slots`` 等)从 network attr 读 —
    DMCInferenceNet 已 expose 这些(同 _server_encode_static 用)。
    """

    requires_network_in_collect = True

    def __init__(
        self,
        *,
        cfg: Any,
        network: torch.nn.Module,
        paradigm_cfg_dict: dict,
        n_actors: int = 1,
        inf_port: Optional[int] = None,
        trans_port: Optional[int] = None,
        io_timeout_ms: int = 30_000,
        socket_forward_builder_path: Optional[str] = None,
        socket_forward_builder_kwargs: Optional[dict] = None,
    ) -> None:
        self.cfg = cfg
        self.network = network
        self.paradigm_cfg_dict = paradigm_cfg_dict
        self.n_actors = int(n_actors)
        self.inf_port = inf_port if inf_port is not None else _free_port()
        self.trans_port = trans_port if trans_port is not None else _free_port()
        self.io_timeout_ms = int(io_timeout_ms)
        # Builder path defaults to production DMC socket decoder;test can override with
        # a stub that bypasses decode_dmc_request(no hook_encoder needed)。
        self._socket_forward_builder_path = (
            socket_forward_builder_path or 'training.paradigms.dmc._socket_decoder.build_dmc_socket_forward_callback'
        )
        self._socket_forward_builder_kwargs = socket_forward_builder_kwargs
        self._weights_version = 0
        self._episode_seq = 0
        self._spawned = False

        # Extract net architecture params for assembler.
        actor_critic = network.net if hasattr(network, 'net') else network
        # Required — 无默认。 静默默认 30 会与网络 action 容量不一致 → 训练 gather OOB
        # (I29 T-R3 bug)。 caller(_make_go_collector / 测试)必须显式提供。
        self._max_actions = int(paradigm_cfg_dict['max_actions'])
        self.assembler = DmcTransitionAssembler(
            n_counter_slots=int(actor_critic.n_counter_slots),
            n_hooks=int(actor_critic.n_hooks),
            max_ops_per_hook=int(actor_critic.max_ops_per_hook),
            fields_per_op=int(actor_critic.fields_per_op),
            max_actions=self._max_actions,
            # 在途 episode 上限 — 健康运行 ≈ n_actors,32x 给足 headroom;超限说明
            # orphaned episode 堆积(actor 死亡遗留),驱逐最久未活跃防泄漏(I29 T-RR.2)。
            max_inflight_episodes=max(256, 32 * self.n_actors),
        )

        self._server: Optional[InferenceServer] = None
        self._backend: Optional[GoActorBackend] = None
        self._trans_listener_thr: Optional[threading.Thread] = None
        self._trans_listener_stop: Optional[threading.Event] = None

    def _bootstrap(self) -> None:
        if self._spawned:
            return

        # InferenceServer with socket listener + DMC forward callback。
        self._server = InferenceServer(
            network=self.network,
            device=str(next(self.network.parameters()).device),
            max_batch=int(getattr(self.cfg.pipeline, 'inference_max_batch', 1)) if hasattr(self.cfg, 'pipeline') else 1,
            batch_timeout_ms=int(getattr(self.cfg.pipeline, 'inference_batch_timeout_ms', 2))
            if hasattr(self.cfg, 'pipeline')
            else 2,
            socket_port=self.inf_port,
            socket_forward_builder_path=self._socket_forward_builder_path,
            socket_forward_builder_kwargs=(
                self._socket_forward_builder_kwargs
                if self._socket_forward_builder_kwargs is not None
                else {'max_actions': self._max_actions}
            ),
        )
        self._server.start(wait_ready_s=15.0)

        # Transition sink listener — feeds assembler。
        ready = threading.Event()
        self._trans_listener_stop = threading.Event()
        self._trans_listener_thr = start_trans_listener(
            self.trans_port, self.assembler.ingest, ready, self._trans_listener_stop
        )
        if not ready.wait(timeout=5.0):
            raise RuntimeError(f'transition sink listener bind timeout port={self.trans_port}')

        # GoActorBackend — start pool。
        self._backend = GoActorBackend()
        self._backend.start_with_config(
            paradigm='dmc',
            n_actors=self.n_actors,
            inf_addr=f'127.0.0.1:{self.inf_port}',
            trans_addr=f'127.0.0.1:{self.trans_port}',
            paradigm_cfg=self.paradigm_cfg_dict,
            io_timeout_ms=self.io_timeout_ms,
        )

        self._spawned = True

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Drain assembler.ready 返 CollectorOutput。 ``provider`` 在 Go 路径不用(actor 内部
        自带 inference_client connect 到 InfServer socket)。"""
        del provider
        self._bootstrap()

        # 异步 Go collector:drain_ready 即时返回当前 assembled。 空时必须 poll-with-
        # sleep 而非立即返回 —— driver 拿空会立刻再调 collect,热自旋持 GIL 饿死同进程
        # transition listener 线程 → assembler ingest 不到 → episodes 卡 0(I29 T-R3
        # 实测 driver 1091 iter/s)。 sleep 释放 GIL 让 listener 跑。
        import time

        _deadline = time.monotonic() + 10.0
        ready = self.assembler.drain_ready()
        while not ready and time.monotonic() < _deadline:
            time.sleep(0.1)
            ready = self.assembler.drain_ready()
        if not ready:
            return CollectorOutput(transitions=[], episode_stats=[], runtime_metrics={'n_dmc_episodes': 0})

        # cap to n_episodes (collector contract)
        ready = ready[: max(1, int(n_episodes))]

        episodes_for_buffer = []
        episode_stats = []
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
                    'source': 'go_actor',
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
        """Publish learner weights to InfServer (via mp.Queue path,socket
        listener 走 same closure-shared network 自动看到新权重)。"""
        self._weights_version += 1
        sd_cpu = {k: v.detach().cpu() for k, v in network.state_dict().items()}
        if self._server is not None:
            self._server.update_network(sd_cpu)
        return self._weights_version

    def close(self) -> None:
        """Order: backend → trans listener → server。"""

        def _safely(fn):
            try:
                fn()
            except Exception:
                pass

        if self._backend is not None:
            _safely(self._backend.stop)
            self._backend = None
        if self._trans_listener_stop is not None:
            stop_trans_listener(self._trans_listener_stop, self._trans_listener_thr)
            self._trans_listener_stop = None
            self._trans_listener_thr = None
        if self._server is not None:
            _safely(self._server.stop)
            self._server = None
        self._spawned = False

    def state_dict(self) -> dict:
        return {'episode_seq': self._episode_seq, 'weights_version': self._weights_version}

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._weights_version = sd.get('weights_version', 0)
