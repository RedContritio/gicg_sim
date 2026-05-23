"""DMCGoActorCollector — Go-native actor pool collector for DMC paradigm。

Wire DMC Go-native actor pool + Python InferenceServer with embedded socket listener
+ Python transition sink listener + DmcTransitionAssembler 全栈,以 ``Collector`` protocol
暴露给 driver。

Architecture(对应 design.md):

    ┌─ Python master ────────────────────────────────────────────────────┐
    │                                                                    │
    │  InferenceServer (mp.Process)                                      │
    │   ├─ socket listener thread (Go → request_q → response)            │
    │   └─ main loop batches socket + mp requests (Route A, T-RR.4)      │
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

import queue
import socket
import threading
import time
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


def _drain_queue_assemble(
    q: 'queue.Queue[_Transition]',
    assembler: DmcTransitionAssembler,
    target: int,
    *,
    deadline_s: float,
) -> list[AssembledEpisode]:
    """从有界 transition queue lazy-ingest 到 assembler,直到组装出 ``target`` 个完整
    episode(或 ``deadline_s`` 墙钟超时)。

    I29 T-RR.3 backpressure 的消费端:**只 ingest 够 target 的数量** —— 余下 raw
    transition 留在 ``q`` 里。 这是 backpressure 成立的关键:``q`` 是唯一 backlog
    蓄水池,collect 不抽干它,故 producer 快于 consumer 时 ``q`` 会涨到 maxsize →
    listener 阻塞 put → socket 回压 → Go actor 限流。 若 collect 把 ``q`` 抽干则无界
    增长只是从 ``q`` 搬到 ``_ready``,backpressure 失效。

    ``assembler.ingest`` 含重 numpy 组装(``_capture_obs_np``),在此(driver 线程)
    跑 —— 不再像旧架构在 listener 线程跑而饿死 driver(穷举审计 #14)。

    deadline 检查在循环顶 **无条件** 执行 —— 即便 ``q`` 持续非空(producer 高速)也
    保证 collect 墙钟有界返回(不只在 ``q`` 空时才检查)。
    """
    deadline = time.monotonic() + deadline_s
    while assembler.n_ready() < target:
        if time.monotonic() >= deadline:
            break
        try:
            t = q.get(timeout=0.1)
        except queue.Empty:
            continue
        assembler.ingest(t)
    return assembler.drain_ready()


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
        # Bounded transition queue —— maxsize 直接决定满载内存 cap。 每条 raw _Transition
        # 含 payload bytes。 wire v3 后(commit 1687f5d 不 pad refs/pay)per-trans 实际
        # ~12 KB(nlegal-sized,前 padded 110 KB 是 96% padding 0)。 4096 cap = ~48 MB,
        # 远 < pre-fix 4096×110 KB = 450 MB,mem 不再 是 issue。
        # **2026-05-24 Win N=16 perf bench 实测**:256 cap 在 Win N=16 × 6.86 push/s/actor
        # = 110 push/s 下 backpressure 永久饱和,transition_writer.push concurrency 7.42
        # (~47% actor blocked,fps 11 vs baseline 25 ~55% loss)。 commit a8123f8 估算
        # 「N=16 × ~5 push/s」错位(实测 1.4x),256 cap 设计假设 unfit。 改 4096 大幅
        # 放宽 backpressure tolerance(48 MB cap 可承)。 producer<<consumer 场景 cap 无关,
        # producer>consumer 长期超时仍会 fail-loud(TransitionWriter 5min 写超时,I29 T-RR.3)。
        trans_queue_maxsize: int = 4096,
    ) -> None:
        self.cfg = cfg
        self.network = network
        self.paradigm_cfg_dict = paradigm_cfg_dict
        self.n_actors = int(n_actors)
        self.inf_port = inf_port if inf_port is not None else _free_port()
        self.trans_port = trans_port if trans_port is not None else _free_port()
        self.io_timeout_ms = int(io_timeout_ms)
        self._weights_version = 0
        self._episode_seq = 0
        self._spawned = False
        # 有界 transition queue — listener thread put,collect()(driver thread)get。
        # 满 → listener 阻塞 put → 停 drain socket → TCP 回压 → Go TransitionWriter.Push
        # 阻塞 → 全 pool 暂停生产。 backlog 内存 O(maxsize):queue 本身 ≤ maxsize 条 raw
        # transition,assembler `_buffers` 持有的在途部分是其组装态、同量级,均有界(对比
        # 旧架构 `_ready` 无界堆 → RSS 10.5GB,I29 T-RR.3 backpressure)。
        self._trans_queue: 'queue.Queue[_Transition]' = queue.Queue(maxsize=int(trans_queue_maxsize))

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

        # InferenceServer — Route A(I29 T-RR.4):socket 请求走 ``request_q`` 批处理。
        # 网络必须是 ``DMCInferenceNet``(``DMCNetwork.__call__`` 故意 raise
        # NotImplementedError;raw ``DMCNetwork`` 不能作 InfServer network)。 镜像
        # ``_mp_internal._spawn_inference_pool`` 的构造:``DMCInferenceNet(actor_critic)``
        # + ``request_decoder_path`` 指向 ``decode_dmc_request`` + ``max_batch`` =
        # n_actors,使 N 个 socket client 的并发请求能批到一起。
        from training.paradigms.dmc.inference_net import DMCInferenceNet

        actor_critic = self.network.net if hasattr(self.network, 'net') else self.network
        dbg = getattr(self.cfg, 'debug', None)
        self._server = InferenceServer(
            network=DMCInferenceNet(actor_critic),
            device=str(next(self.network.parameters()).device),
            max_batch=max(1, self.n_actors),
            batch_timeout_ms=int(getattr(self.cfg.pipeline, 'inference_batch_timeout_ms', 2))
            if hasattr(self.cfg, 'pipeline')
            else 2,
            request_decoder_path='training.paradigms.dmc.mp_factories.decode_dmc_request',
            socket_port=self.inf_port,
            socket_max_actions=self._max_actions,
            socket_clients=self.n_actors,
            perf_trace_enabled=bool(getattr(dbg, 'perf_trace', False)) if dbg else False,
            perf_trace_flush_n=int(getattr(dbg, 'perf_trace_flush_n', 200)) if dbg else 200,
            perf_trace_flush_s=float(getattr(dbg, 'perf_trace_flush_s', 1.0)) if dbg else 1.0,
            perf_trace_dir=getattr(dbg, 'perf_trace_dir', None) if dbg else None,
        )
        self._server.start(wait_ready_s=15.0)

        # Transition sink listener — feeds 有界 queue(非直接 assembler.ingest)。
        # listener thread 只做轻活(recv + 解 envelope + put);重组装(_capture_obs_np)
        # 移到 collect() 的 driver 线程,不再饿死 driver(I29 T-RR.3 / 审计 #14)。
        ready = threading.Event()
        self._trans_listener_stop = threading.Event()
        self._trans_listener_thr = start_trans_listener(
            self.trans_port, self._enqueue, ready, self._trans_listener_stop
        )
        if not ready.wait(timeout=5.0):
            raise RuntimeError(f'transition sink listener bind timeout port={self.trans_port}')

        # GoActorBackend — start pool。 cfg.runtime.actor_lib_path optional
        # 显式 override(post 2026-05-24 GICG_ACTOR_LIB env var 砍 — cfg-driven)。
        rt = getattr(self.cfg, 'runtime', None)
        actor_lib_path = getattr(rt, 'actor_lib_path', None) if rt else None
        self._backend = GoActorBackend(lib_path=actor_lib_path)
        self._backend.start_with_config(
            paradigm='dmc',
            n_actors=self.n_actors,
            inf_addr=f'127.0.0.1:{self.inf_port}',
            trans_addr=f'127.0.0.1:{self.trans_port}',
            paradigm_cfg=self.paradigm_cfg_dict,
            io_timeout_ms=self.io_timeout_ms,
        )

        self._spawned = True

    def _enqueue(self, t: _Transition) -> None:
        """Transition sink listener callback — raw transition 推进有界 queue。

        queue 满 → 阻塞重试(= backpressure:listener 停 drain socket → Go Push 阻塞)。
        stop event(close 中 set)→ 丢弃返回,使 listener handler 不被卡死、socket 得以
        drain、Go Push 解阻塞,StopPool 的 wg.Wait() 不 hang。
        """
        stop = self._trans_listener_stop
        while True:
            # stop is None —— listener 已拆除(close 末置 None);视同停机,丢弃。
            if stop is None or stop.is_set():
                return  # shutting down — drop
            try:
                self._trans_queue.put(t, timeout=0.5)
                return
            except queue.Full:
                continue

    def collect(self, n_episodes: int, provider: Any) -> CollectorOutput:
        """Lazy-drain 有界 transition queue → assemble → CollectorOutput。 ``provider``
        在 Go 路径不用(actor 内部自带 inference_client connect 到 InfServer socket)。"""
        del provider
        self._bootstrap()

        # _drain_queue_assemble 只 ingest 够 n_episodes 的 transition,余下留 queue
        # (backpressure 蓄水池)。 q.get(timeout) 阻塞等待 — 既不热自旋也不饿死 listener。
        target = max(1, int(n_episodes))
        ready = _drain_queue_assemble(self._trans_queue, self.assembler, target, deadline_s=10.0)
        if not ready:
            return CollectorOutput(transitions=[], episode_stats=[], runtime_metrics={'n_dmc_episodes': 0})

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
                # backpressure 诊断:queue 深度接近 maxsize = consumer 落后 producer。
                'trans_queue_depth': self._trans_queue.qsize(),
            },
            n_units=n_trans_total,
        )

    def sync_weights(self, network: Any) -> int:
        """Publish learner weights to InfServer (via mp.Queue 'weights' path)。

        InfServer 的 network 是 ``DMCInferenceNet(actor_critic)`` —— 其 state_dict
        key 带 ``net.`` 前缀(``DMCInferenceNet`` 通过 ``add_module('net', ...)`` 注册
        ActorCritic)。 故这里推 ``net.``-前缀的 actor_critic state_dict,与 InfServer
        network.load_state_dict 的 key 命名空间对齐。"""
        self._weights_version += 1
        actor_critic = network.net if hasattr(network, 'net') else network
        sd_cpu = {'net.' + k: v.detach().cpu() for k, v in actor_critic.state_dict().items()}
        if self._server is not None:
            self._server.update_network(sd_cpu)
        return self._weights_version

    def close(self) -> None:
        """Order: trans listener stop(set first)→ backend → join listener → server。

        必须先 set listener stop event:此后 ``_enqueue`` 改为丢弃(不再阻塞在满 queue
        的 put)→ listener handler 继续 drain socket → Go ``TransitionWriter.Push`` 不被
        backpressure 卡住 → ``StopPool`` 的 ``wg.Wait()`` 不 hang(I29 T-RR.3)。
        """

        def _safely(fn):
            try:
                fn()
            except Exception:
                pass

        # 1. set listener stop —— _enqueue 即刻改为丢弃,解除 socket 回压。
        if self._trans_listener_stop is not None:
            self._trans_listener_stop.set()
        # 2. stop Go pool —— actor 此时不会卡在 Push,ctx cancel 后干净退出。
        if self._backend is not None:
            _safely(self._backend.stop)
            self._backend = None
        # 3. join listener thread。
        if self._trans_listener_stop is not None:
            stop_trans_listener(self._trans_listener_stop, self._trans_listener_thr)
            self._trans_listener_stop = None
            self._trans_listener_thr = None
        # 4. stop InfServer。
        if self._server is not None:
            _safely(self._server.stop)
            self._server = None
        self._spawned = False

    def state_dict(self) -> dict:
        return {'episode_seq': self._episode_seq, 'weights_version': self._weights_version}

    def load_state_dict(self, sd: dict) -> None:
        self._episode_seq = sd.get('episode_seq', 0)
        self._weights_version = sd.get('weights_version', 0)
