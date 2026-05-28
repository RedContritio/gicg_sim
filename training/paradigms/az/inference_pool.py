"""Parallel self-play worker pool backed by a central inference server.

Workers are lightweight MCTS-tree-only processes that route every
network evaluation through an ``InferenceServer`` over
``multiprocessing.Pipe``. The worker loop lives in
``inference_worker.py``; this module owns the main-process handle.
"""

from __future__ import annotations

import atexit
import multiprocessing as mp
import os
import queue as queue_mod
import signal
import time
from typing import TYPE_CHECKING, Optional

from training.paradigms.az.inference_worker import worker_loop as _worker_loop
from training.core.inference.server import (
    InferenceServer,
    InferenceServerConfig,  # noqa: F401
)

if TYPE_CHECKING:
    from training.paradigms.az.config import AZConfig


class WorkerError(RuntimeError):
    """Raised on main when a worker's result carries an error field."""


class PoolDeadlock(RuntimeError):
    """Raised by ``ParallelInferencePool.next_result`` when the pool
    cannot deliver any more results."""


class ParallelInferencePool:
    """Owns one InferenceServer + N worker processes for parallel self-play."""

    _HEARTBEAT_THRESHOLD_S = 10.0
    _NEXT_RESULT_POLL_S = 1.0

    def __init__(self, cfg: 'AZConfig'):
        self.cfg = cfg
        n_workers = int(cfg.n_workers)
        if n_workers <= 0:
            raise ValueError(f'n_workers must be positive, got {n_workers}')

        self._ctx = mp.get_context('spawn')
        self.server = InferenceServer(
            agent_config=cfg.agent,
            n_workers=n_workers,
            server_cfg=cfg.inference,
            # W2-1: pre-W2 the server-loop hard-imported AZ Agent;now it
            # resolves the factory via this path. AZ paradigm 自报 own
            # Agent class — keeps core/ free of paradigm-specific imports。
            network_factory_path='training.paradigms.az.network.Agent',
            # W2-2: drain.py 的 game_start + eval_batch handler 也是 AZ-shaped,
            # 同样路径化注入(audit finding 高优 #2)。
            inference_handlers_module_path='training.paradigms.az._inference_handlers',
        )
        self._result_queue: 'mp.Queue' = self._ctx.Queue()
        self._cmd_queues: list['mp.Queue'] = []
        self._worker_procs: list[mp.Process] = []
        self._n_workers = n_workers
        self._round_robin = 0
        self._started = False

        self._heartbeat_ts = self._ctx.Array('d', n_workers, lock=False)
        self._n_dispatched = 0
        self._n_consumed = 0

    def start(self) -> None:
        if self._started:
            raise RuntimeError('pool already started')
        self.server.start()
        now = time.time()
        for wid in range(self._n_workers):
            self._heartbeat_ts[wid] = now
            cmd_q: 'mp.Queue' = self._ctx.Queue()
            pipe = self.server.get_worker_pipe(wid)
            proc = self._ctx.Process(
                target=_worker_loop,
                args=(
                    wid,
                    self.cfg,
                    pipe,
                    cmd_q,
                    self._result_queue,
                    self._heartbeat_ts,
                ),
                daemon=False,
            )
            proc.start()
            self._cmd_queues.append(cmd_q)
            self._worker_procs.append(proc)
        self._started = True

        atexit.register(self._emergency_cleanup)
        try:
            self._prev_sigterm = signal.signal(signal.SIGTERM, self._on_sigterm)
            self._prev_sigint = signal.signal(signal.SIGINT, self._on_sigterm)
        except ValueError:
            self._prev_sigterm = None
            self._prev_sigint = None

    def _on_sigterm(self, signum, frame):
        try:
            self._emergency_cleanup()
        finally:
            signal.signal(signum, signal.SIG_DFL)
            os.kill(os.getpid(), signum)

    def _emergency_cleanup(self) -> None:
        if not self._started:
            return
        for p in self._worker_procs:
            try:
                if p.is_alive():
                    p.terminate()
            except Exception:
                pass
        for p in self._worker_procs:
            try:
                p.join(timeout=2.0)
                if p.is_alive():
                    p.kill()
            except Exception:
                pass
        self._worker_procs.clear()
        self._cmd_queues.clear()
        try:
            self.server.stop(wait_timeout_s=2.0)
        except Exception:
            pass
        self._started = False

    def dispatch(self, game_idx: int, env_seed: int) -> None:
        if not self._started:
            raise RuntimeError('pool not started')
        wid = self._round_robin % self._n_workers
        self._round_robin += 1
        self._cmd_queues[wid].put(
            {
                'kind': 'play',
                'game_idx': game_idx,
                'env_seed': env_seed,
            }
        )
        self._n_dispatched += 1

    def alive_workers(self) -> int:
        if not self._started:
            return 0
        now = time.time()
        n = 0
        for wid in range(self._n_workers):
            if wid >= len(self._worker_procs):
                continue
            proc = self._worker_procs[wid]
            last_beat = float(self._heartbeat_ts[wid])
            if now - last_beat < self._HEARTBEAT_THRESHOLD_S and proc.is_alive():
                n += 1
        return n

    def dispatched_count(self) -> int:
        return self._n_dispatched

    def consumed_count(self) -> int:
        return self._n_consumed

    def next_result(self, timeout: Optional[float] = None) -> dict:
        if not self._started:
            raise RuntimeError('pool not started')
        deadline = None if timeout is None else time.time() + timeout
        while True:
            remaining = None if deadline is None else max(0.0, deadline - time.time())
            poll = self._NEXT_RESULT_POLL_S
            if remaining is not None:
                poll = min(poll, remaining)
            try:
                res = self._result_queue.get(timeout=poll)
            except queue_mod.Empty:
                alive = self.alive_workers()
                if alive < self._n_workers and self._n_dispatched > self._n_consumed:
                    raise PoolDeadlock(
                        f'pool cannot deliver more results: '
                        f'alive={alive}/{self._n_workers}, '
                        f'dispatched={self._n_dispatched}, '
                        f'consumed={self._n_consumed}'
                    )
                if deadline is not None and time.time() >= deadline:
                    raise TimeoutError(f'no worker result within {timeout}s')
                continue
            if 'error' in res:
                raise WorkerError(f'worker {res["worker_id"]} crashed: {res["error"]}\n{res.get("traceback", "")}')
            self._n_consumed += 1
            return res

    def push_weights(self, cpu_state_dict: dict) -> None:
        if not self._started:
            raise RuntimeError('pool not started')
        self.server.push_weights(cpu_state_dict)

    @property
    def stats_queue(self):
        return self.server.stats_queue

    def stop(self, wait_timeout_s: float = 10.0) -> None:
        if not self._started:
            return
        for q in self._cmd_queues:
            try:
                q.put({'kind': 'stop'}, timeout=1.0)
            except queue_mod.Full:
                pass
        t0 = time.perf_counter()
        for p in self._worker_procs:
            remaining = max(0.1, wait_timeout_s - (time.perf_counter() - t0))
            p.join(timeout=remaining)
            if p.is_alive():
                p.terminate()
                p.join(timeout=1.0)
        self._worker_procs.clear()
        self._cmd_queues.clear()
        self.server.stop(wait_timeout_s=wait_timeout_s)
        self._started = False

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
