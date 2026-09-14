"""Atomically launch inference, Go actors, and transition SHM.

The topology consists of one inference process, ``N`` independent
``cmd/gicg_actor`` subprocesses, and one shared multiple-producer transition
ring. Each Go process hosts one actor, connects to inference over TCP, and
publishes raw wire frames to the ring.

Partial startup cleans up every process and SHM object already created.
Shutdown signals all actors first, waits for them, closes transition SHM,
and stops inference last so in-flight actor requests can finish.
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
    """Find the repository root relative to this module."""
    return Path(__file__).resolve().parents[3]


def _free_port() -> int:
    """Ask the OS for an unused loopback TCP port."""
    import socket as _socket

    s = _socket.socket(_socket.AF_INET, _socket.SOCK_STREAM)
    s.bind(('127.0.0.1', 0))
    port = s.getsockname()[1]
    s.close()
    return port


@dataclass
class PipelineHandle:
    """Handles needed to shut down the launched topology.

    fields:
      - server: InferenceServer mp.Process handle (network forward + socket listener)
      - go_procs: list of GoSubprocessHandle — N independent Go OS subprocess (each
        NActors=1 + BaseActorID=i ∈ [0, N)).
      - trans_channel: owner of the shared transition ring.
      - inf_port / shm_ring_name: diagnostic connection identifiers.
    """

    server: InferenceServer
    go_procs: list[GoSubprocessHandle]
    trans_channel: TransitionShmChannel
    inf_port: int
    shm_ring_name: str

    @property
    def n_actors(self) -> int:
        """Number of independent Go actor subprocesses."""
        return len(self.go_procs)

    def shutdown(self, *, go_timeout_s: float = 10.0, server_timeout_s: float = 5.0) -> None:
        """Stop actors, close transition SHM, then stop inference.

        Signals are sent to all actors before sequential joins so their grace
        periods overlap. Cleanup continues after individual failures.
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
    socket_payload_encoder_path: str,
    binary_path: Optional[str] = None,
    tuning: Optional[PipelineTuningCfg] = None,
    device: Optional[str] = None,
) -> PipelineHandle:
    """Start inference, a shared transition ring, and ``n_actors`` processes.

    Args:
        network: module hosted by the inference server.
        paradigm_name: Go paradigm registry key.
        paradigm_config: mapping serialized for ``paradigm.Configure``.
        n_actors: number of independent one-actor Go subprocesses.
        shm_ring_name: shared transition-ring name.
        inf_max_actions: action capacity used by the socket adapter.
        request_decoder_path: dotted "module.attr" for InfServer-side decoder
        socket_payload_encoder_path: dotted request encoder for the socket wire.
        binary_path: optional actor executable; defaults to ``bin/gicg_actor``
            or ``bin/gicg_actor.exe``.
        tuning: SHM, batching, timeout, polling, and Go runtime settings.
        device: explicit inference device overriding ``tuning.device``.

    Returns:
        Handles for transition reads and coordinated shutdown.

    Raises:
        RuntimeError: inference startup or actor readiness fails.
        FileNotFoundError: the actor executable does not exist.
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
            f'spawn_pipeline: binary {binary_path} not found — '
            f"run 'go build -o bin/gicg_actor ./cmd/gicg_actor' (POSIX) "
            f"or 'go build -o bin\\gicg_actor.exe .\\cmd\\gicg_actor' (Win) first"
        )

    if tuning is None:
        tuning = PipelineTuningCfg()
    # Explicit device overrides the tuning bundle.
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
        socket_payload_encoder_path=socket_payload_encoder_path,
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
                # Zero requests the Go runtime's unbounded default.
                'go_mem_limit_mb': int(tuning.go_mem_limit_mb),
                'inf_server_addr': f'127.0.0.1:{inf_port}',
            }
            go_proc = GoSubprocessHandle.spawn(
                binary_path,
                subproc_cfg,
                ready_timeout_s=tuning.ready_timeout_s,
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
    """Generate a short SHM name within the macOS POSIX limit.

    Format: ``<prefix>_<pid_hex4>_<mono_hex6>``,典型 14 字节 (i29_t_1234_abcdef)。
    PID plus the monotonic clock avoid collisions across concurrent runs.
    """
    ts = int(time.monotonic_ns()) & 0xFFFFFF
    pid_hex = f'{os.getpid() & 0xFFFF:04x}'
    return f'{prefix}_{pid_hex}_{ts:06x}'
