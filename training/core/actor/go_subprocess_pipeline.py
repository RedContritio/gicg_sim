"""GoSubprocessPipeline — InfServer + N independent Go subprocess + shared SHM trans channel atomic spawn。

I29 R7.2 (2026-05-25) — N+2 OS process topology mirror Python mp。

把三件套(InfServer + N Go subprocess + 1 shared SHM ring)打包:master Python spawns
InferenceServer mp.Process,然后 create shared SHM trans ring + spawn **N independent
Go subprocess**(各 cmd/gicg_actor with NActors=1,BaseActorID = i)。 每 Go subprocess
attach 同一 SHM trans ring(MPSC,N producer)+ 起 1 TCP InferenceClient 到 InfServer +
跑 1 actor goroutine。 master 轮询 SHM ring (try_pop_with_meta) 拿 raw wire frame bytes。
Inference 走 TCP(I29 R7.1 删 SHM inference path,与 Python mp wire 等价)。

为什么 N independent subprocess(而非 1 subprocess containing N goroutine):

  R1 audit(Python mp 架构)findings: Python mp = N+2 truly independent OS process
  (spawn ctx,1 master + N actor + 1 InfServer)。 R7.2 前 Go subprocess 是 1 process
  containing N goroutine — collapse N+2 → 2 processes,forfeit OS-level parallelism +
  inter-actor GIL/scheduler contention。 R7.2 起 N independent subprocess,each
  NActors=1 + BaseActorID = i,跨 subprocess clientID 唯一(BaseActorID + local_idx = i),
  与 Python mp 完全等价 N+2 拓扑。

Lifecycle(atomic):
  - spawn_pipeline(...) → spawn InfServer → wait ready → create_owner SHM trans ring →
    spawn N Go subprocess(各 BaseActorID=i + NActors=1)→ each wait READY → 返
    PipelineHandle(list[GoSubprocessHandle] + 1 SHM ring + 1 InfServer)。 partial spawn
    failure(第 k 个 subprocess 启动失败)atomic cleanup 已 spawned 的 0..k-1 + ring + InfServer。
  - PipelineHandle.shutdown() → SIGTERM N Go subprocess(parallel)→ wait join
    (sequential)→ close SHM trans ring → stop InfServer。 全 try/except — 单 failure
    不阻塞后续 cleanup。

I29 redesign P3 ship (2026-05-25):本 module 是 cfg-driven dispatch
(`DMCParadigm._make_go_collector` → `DMCGoSubprocessCollector` → `spawn_pipeline`) 的
生产入口。 module API 故意 paradigm-agnostic (network + paradigm_name +
paradigm_config_json),Phase 2 AZ/PPO port 时只需 register paradigm 不重写 spawn 逻辑。

deal-breaker invariant #1 of I29 spec: master 进程 0 cgo lib loaded。 InferenceServer 是
mp.Process subprocess (load torch / cuda there),Go-actor 是 N 个独立 OS subprocess
(load Go runtime there);master driver thread 只用 python-stdlib + numpy + SHM。
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import torch.nn as nn

from training.core.actor.go_subprocess import GoSubprocessHandle
from training.core.actor.inference_server import InferenceServer
from training.core.actor.pipeline_tuning_cfg import PipelineTuningCfg
from training.core.actor.transition_shm_channel import TransitionShmChannel


def _repo_root() -> Path:
    """Find repo root by walking up from this file (training/core/actor/...)。"""
    return Path(__file__).resolve().parents[3]


def _free_port() -> int:
    """Get an unused localhost port (bind 0 + read assigned)。 InfServer socket listener
    需 free port (test 跑并行多 instance 时避免冲突)。"""
    import socket as _socket

    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass
class PipelineHandle:
    """Multi-handle wrapper for atomic shutdown of N+2 process topology (I29 R7.2)。

    fields:
      - server: InferenceServer mp.Process handle (network forward + socket listener)
      - go_procs: list of GoSubprocessHandle — N independent Go OS subprocess (each
        NActors=1 + BaseActorID=i ∈ [0, N))。 mimic Python mp 的 N actor 拓扑。
      - trans_channel: TransitionShmChannel owner (master 端 try_pop_with_meta,
        MPSC ring,N Go subprocess 各 attach 同一 ring name)
      - inf_port / shm_ring_name: debug 诊断用
    """

    server: InferenceServer
    go_procs: list[GoSubprocessHandle]
    trans_channel: TransitionShmChannel
    inf_port: int
    shm_ring_name: str

    @property
    def n_actors(self) -> int:
        """Number of independent Go subprocess (= len(go_procs))。 测试 / 诊断辅助 accessor。"""
        return len(self.go_procs)

    def shutdown(self, *, go_timeout_s: float = 10.0, server_timeout_s: float = 5.0) -> None:
        """Order: N Go subprocess SIGTERM(parallel)→ wait join(sequential)→ SHM
        trans close → InfServer stop。

        Go 必须先停 — InfServer 仍可处理 in-flight inference (Go actor 退出前可能正发请求),
        early stop InfServer 会让 Go actor 收到 socket EOF panic。 trans channel close
        在 Go 死后 — close 会 unlink SHM block,Go 已死不影响。 InfServer last — 它的
        socket listener thread 释放 port。

        N subprocess SIGTERM 走 parallel(``_send_sigterm_only`` non-blocking),wait join
        走 sequential(``terminate`` 内部 wait_timeout)。 这样总 wall ≈ max(per-proc-shutdown)
        而非 N × per-proc-shutdown — N=4 + 5s per proc,parallel = 5s 而非 20s。

        全 try/except — 保单一失败不阻塞后续 cleanup。
        """
        import signal as _signal

        # 1. Parallel SIGTERM 给所有还活着的 Go subprocess。 non-blocking — 仅 send signal,
        #    后面 wait 那步阻塞 join。
        for go_proc in self.go_procs:
            try:
                if go_proc.alive():
                    go_proc._proc.send_signal(_signal.SIGTERM)
            except Exception as exc:  # noqa: BLE001 — diagnostic only
                print(f'[GoSubprocessPipeline] go_proc SIGTERM err: {exc}', file=sys.stderr)

        # 2. Sequential wait join — each go_proc.terminate 内部已 send SIGTERM(idempotent
        #    重发)+ wait timeout + SIGKILL fallback。 我们 step 1 已发 SIGTERM 触发了
        #    graceful 退出 ctx,这里 terminate 主要走 wait 路径。
        for i, go_proc in enumerate(self.go_procs):
            try:
                go_proc.terminate(timeout_s=go_timeout_s)
            except Exception as exc:  # noqa: BLE001
                print(f'[GoSubprocessPipeline] go_procs[{i}].terminate err: {exc}', file=sys.stderr)

        try:
            self.trans_channel.close()
        except Exception as exc:  # noqa: BLE001
            print(f'[GoSubprocessPipeline] trans_channel.close err: {exc}', file=sys.stderr)
        try:
            self.server.stop(timeout_s=server_timeout_s)
        except Exception as exc:  # noqa: BLE001
            print(f'[GoSubprocessPipeline] server.stop err: {exc}', file=sys.stderr)


def spawn_pipeline(
    *,
    network: nn.Module,
    paradigm_name: str,
    paradigm_config: dict[str, Any],
    n_actors: int,
    shm_ring_name: str,
    inf_max_actions: int,
    request_decoder_path: str,
    binary_path: Optional[str] = None,
    # C1 refactor (2026-05-26):tuning 字段全收 PipelineTuningCfg。 None → 全 default
    # (production caller `_make_go_collector` 用此)。 override via
    # `PipelineTuningCfg(shm_capacity=16, device='cpu')` (test fixture)。
    tuning: Optional[PipelineTuningCfg] = None,
    device: Optional[str] = None,
) -> PipelineHandle:
    """Atomic spawn of InfServer + N independent Go subprocess + shared SHM trans channel。

    I29 R7.2 (2026-05-25):N+2 OS process topology — N Go subprocess each NActors=1 +
    BaseActorID=i ∈ [0, N),各 attach 同一 SHM ring (MPSC,master single consumer)。
    与 Python mp `mp.Process(target=actor_main)` × N + InfServer mp.Process 完全等价
    N+2 拓扑,无 OS-level GIL/scheduler contention 跨 actor。

    Caller 责:network 已构造 (production wrap 是 ``DMCInferenceNet(actor_critic)``);
    paradigm_config dict 符合 paradigm-side schema (DMC schema 见
    gicg_actor/dmc/paradigm.go:DMCConfig)。

    Args:
        network: InfServer hosts this nn.Module (forwards inference requests batched)。
        paradigm_name: Go side registry lookup key ("dmc" / "az" / "ppo")。
        paradigm_config: dict serialized to JSON,透传给 Go paradigm.Configure。
        n_actors: 起 N independent Go subprocess(R7.2 起的语义变化)— 每 subprocess
            NActors=1,actor index ∈ [0, n_actors)。 InfServer socket_clients = n_actors。
        shm_ring_name: SHM block 名 (Mac POSIX shm_open 31-byte 名限制,caller 短前缀 + 唯一)。
            N Go subprocess 各 attach by name(同名 = 同 ring,MPSC push)。
        shm_capacity: SHM ring slot 数 (≥ peak inflight episode batches × n_actors)。
        shm_slot_size: SHM per-slot 字节上限 (DMC episode batch ~150 KB,留 headroom 1 MB)。
        inf_max_actions: paradigm action 容量 (DMC 2048),InfServer socket adapter 用。
        request_decoder_path: dotted "module.attr" for InfServer-side decoder
            (DMC = 'training.paradigms.dmc.mp_factories.decode_dmc_request')。
        inf_max_batch: InfServer batch size (default n_actors,batch 满即 forward)。
        inf_batch_timeout_ms: InfServer batch 填满前最大等待时间 ms。
        binary_path: cmd/gicg_actor binary 路径 (default repo_root/bin/gicg_actor)。
        ready_timeout_s: Go subprocess READY 信号超时 (含 InferenceClient connect)。
            N subprocess 走 sequential wait READY,total wall ≈ N × per-subproc cold start
            (Go cold start ~ms,InfServer 已 ready 时 inf connect ~ms,N=4 total 几百 ms)。
        io_timeout_ms: Go subprocess TCP I/O deadline (传给 InferenceClient)。
        device: InfServer torch device (cpu / cuda:0 / mps)。

    Returns:
        PipelineHandle with N go_procs + shared trans_channel + InfServer,for
        ``trans_channel.try_pop`` + ``shutdown``。

    Raises:
        RuntimeError: InfServer 启动失败 / Go subprocess READY 超时 / binary 不存在。
        FileNotFoundError: binary_path 不存在。
    """
    if n_actors <= 0:
        raise ValueError(f'spawn_pipeline: n_actors must be > 0, got {n_actors}')

    if binary_path is None:
        # Win build (build_engine.py) 输出 bin/gicg_actor.exe;POSIX 输出 bin/gicg_actor。
        # 自动 probe — .exe 优先 (Win),fallback 到 no-ext (POSIX)。
        candidate_exe = _repo_root() / 'bin' / 'gicg_actor.exe'
        candidate_posix = _repo_root() / 'bin' / 'gicg_actor'
        if candidate_exe.exists():
            binary_path = str(candidate_exe)
        else:
            binary_path = str(candidate_posix)
    if not os.path.exists(binary_path):
        raise FileNotFoundError(
            f"spawn_pipeline: binary {binary_path} not found — "
            f"run 'go build -o bin/gicg_actor ./cmd/gicg_actor' (POSIX) "
            f"or 'go build -o bin\\gicg_actor.exe .\\cmd\\gicg_actor' (Win) first"
        )

    if tuning is None:
        tuning = PipelineTuningCfg()
    # device 优先 explicit param (collector 已 resolve 过) > tuning.device > 'cpu' fallback
    resolved_device = device or tuning.device or 'cpu'

    # ─── Step 1: spawn InfServer ─────────────────────────────────────────
    # TCP inference only (I29 R7.1 删 SHM inference path) — InfServer 起 socket_listener
    # thread accept N Go-actor TCP client + 进 request_q,与 Python mp.Queue 客户端共用
    # batch forward path,无 bridge layer。 R7.2 N independent subprocess 各起 1 TCP
    # connection → socket_clients = n_actors 不变(server 端配置 N response_qs)。
    inf_port = _free_port()
    server = InferenceServer(
        network=network,
        device=resolved_device,
        max_batch=max(1, tuning.inf_max_batch or n_actors),
        batch_timeout_ms=int(tuning.inf_batch_timeout_ms),
        request_decoder_path=request_decoder_path,
        socket_port=inf_port,
        socket_max_actions=int(inf_max_actions),
        socket_clients=int(n_actors),
    )
    try:
        server.start(wait_ready_s=tuning.ready_timeout_s)
    except Exception:
        # InfServer 启动失败 — 让 caller 看到原 exception (含 traceback)。 无需 explicit cleanup
        # since server.start() 内部已自处。
        raise

    # ─── Step 2: create shared SHM trans channel (owner = master) ────────
    # 单一 ring,N Go subprocess 各 attach by name → MPSC push,master single consumer。
    try:
        trans_channel = TransitionShmChannel.create_owner(
            shm_ring_name,
            capacity=int(tuning.shm_capacity),
            slot_size=int(tuning.shm_slot_size),
        )
    except Exception:
        # SHM create 失败 — InfServer 已 spawn,清理之。
        try:
            server.stop()
        except Exception:
            pass
        raise

    # ─── Step 3: spawn N independent Go subprocess ───────────────────────
    # 各 subprocess NActors=1 + BaseActorID=i ∈ [0, N) — 跨 subprocess clientID 唯一,
    # SHM ring 上 (cid, ep_id) key 不撞。 spawn 顺序 sequential — 每个 spawn 等 READY
    # 才进下一个(避免 N 并发 spawn 触发 InfServer accept race + Go cold start CPU 抢)。
    # partial spawn failure(第 k 个失败)→ atomic cleanup 0..k-1 + SHM + InfServer。
    cfg_json = json.dumps(paradigm_config)
    go_procs: list[GoSubprocessHandle] = []
    try:
        for actor_idx in range(int(n_actors)):
            subproc_cfg: dict[str, Any] = {
                # 每 subprocess 单 actor goroutine — N independent OS subprocess 拓扑。
                'n_actors': 1,
                'base_actor_id': int(actor_idx),
                'trans_shm_name': shm_ring_name,
                'trans_shm_capacity': int(tuning.shm_capacity),
                'trans_shm_slot_size': int(tuning.shm_slot_size),
                'paradigm_name': paradigm_name,
                'paradigm_config': cfg_json,
                'io_timeout_ms': int(tuning.io_timeout_ms),
                'go_gomaxprocs': int(tuning.go_gomaxprocs),
                'inf_server_addr': f'127.0.0.1:{inf_port}',
            }
            go_proc = GoSubprocessHandle.spawn(
                binary_path,
                subproc_cfg,
                ready_timeout_s=tuning.ready_timeout_s,
                go_mem_limit=tuning.go_mem_limit or None,
            )
            go_procs.append(go_proc)
    except Exception:
        # Partial spawn failure — 清理已 spawn 的 0..k-1 + SHM + InfServer。 propagate 原 exception
        # 让 caller 看到 RuntimeError + stderr 诊断。
        import signal as _signal

        for proc in go_procs:
            try:
                if proc.alive():
                    proc._proc.send_signal(_signal.SIGTERM)
            except Exception:
                pass
        for proc in go_procs:
            try:
                proc.terminate(timeout_s=5.0)
            except Exception:
                pass
        try:
            trans_channel.close()
        except Exception:
            pass
        try:
            server.stop()
        except Exception:
            pass
        raise

    return PipelineHandle(
        server=server,
        go_procs=go_procs,
        trans_channel=trans_channel,
        inf_port=inf_port,
        shm_ring_name=shm_ring_name,
    )


def make_unique_shm_name(prefix: str = 'i29_t') -> str:
    """Generate short unique SHM ring name (Mac POSIX shm_open 31-byte 名限制)。

    Format: ``<prefix>_<pid_hex4>_<mono_hex6>``,典型 14 字节 (i29_t_1234_abcdef)。
    跨 test / 跨 run 不重 (pid + monotonic_ns 联合)。
    """
    ts = int(time.monotonic_ns()) & 0xFFFFFF
    pid_hex = f'{os.getpid() & 0xFFFF:04x}'
    return f'{prefix}_{pid_hex}_{ts:06x}'
