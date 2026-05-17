"""Multiprocess CFR trainer."""

from __future__ import annotations

import multiprocessing as mp
import queue as queue_mod
import time

from training.paradigms.cfr._collect_helpers import ingest_batches
from training.paradigms.cfr.strategy_net import CFRNetConfig
from training.paradigms.cfr.train import (
    CFRTrainConfig,
    CFRTrainer,
)
from training.paradigms.cfr.worker import (
    WorkError,
    WorkItem,
    WorkResult,
    WorkerConfig,
    spawn_worker,
)


def _unused_env_factory(_seed: int):
    raise RuntimeError('ParallelCFRTrainer does not use the central env_factory — traversal runs in worker processes.')


class ParallelCFRTrainer(CFRTrainer):
    """CFR trainer that farms traversals out to N worker processes."""

    def __init__(
        self,
        net_cfg: CFRNetConfig,
        train_cfg: CFRTrainConfig,
        worker_cfg: WorkerConfig,
        n_workers: int,
        worker_timeout_s: float = 900.0,
    ):
        if n_workers < 1:
            raise ValueError(f'n_workers must be >= 1, got {n_workers}')
        if (
            worker_cfg.traversal.epsilon != train_cfg.traversal.epsilon
            or worker_cfg.traversal.max_game_steps != train_cfg.traversal.max_game_steps
            or worker_cfg.traversal.importance_weight_max != train_cfg.traversal.importance_weight_max
        ):
            raise ValueError(
                'worker_cfg.traversal must match train_cfg.traversal (epsilon, max_game_steps, importance_weight_max)'
            )
        super().__init__(
            net_cfg=net_cfg,
            train_cfg=train_cfg,
            env_factory=_unused_env_factory,
        )
        self.n_workers = n_workers
        self.worker_cfg = worker_cfg
        self.worker_timeout_s = worker_timeout_s

        self._mp_ctx = mp.get_context('spawn')
        self._in_qs: list[mp.Queue] = [self._mp_ctx.Queue() for _ in range(n_workers)]
        self._out_q: mp.Queue = self._mp_ctx.Queue()
        self._procs: list[mp.Process] = [
            spawn_worker(i, worker_cfg, self._in_qs[i], self._out_q) for i in range(n_workers)
        ]

        self._shutdown_done = False

    def _assert_workers_alive(self) -> None:
        for i, p in enumerate(self._procs):
            if not p.is_alive():
                raise RuntimeError(
                    f'ParallelCFRTrainer: worker {i} (pid {p.pid}) has '
                    f'exited with code {p.exitcode}; cannot dispatch work.'
                )

    def _run_traversals(self, iteration: int) -> None:
        K = self.train_cfg.traversals_per_iteration
        if K <= 0:
            return

        self._assert_workers_alive()

        for net in self.advantage_nets:
            net.eval()

        base = K // self.n_workers
        extra = K % self.n_workers
        per_worker = [base + (1 if i < extra else 0) for i in range(self.n_workers)]

        weights_per_player = [
            {k: v.detach().cpu().clone() for k, v in net.state_dict().items()} for net in self.advantage_nets
        ]

        global_idx = 0
        seed_base_iter = 1_000_000 * iteration
        active_workers = 0
        for wi, n in enumerate(per_worker):
            if n == 0:
                continue
            traverser_seq = [self._pick_traverser(iteration, global_idx + k) for k in range(n)]
            self._in_qs[wi].put(
                WorkItem(
                    weights_per_player=weights_per_player,
                    n_traversals=n,
                    iteration=iteration,
                    seed_base=seed_base_iter + global_idx * 1000,
                    traverser_seq=traverser_seq,
                )
            )
            global_idx += n
            active_workers += 1

        all_batches: list = []
        t_deadline = time.perf_counter() + self.worker_timeout_s
        for _ in range(active_workers):
            remaining = t_deadline - time.perf_counter()
            if remaining <= 0:
                raise TimeoutError(f'ParallelCFRTrainer: worker result timeout after {self.worker_timeout_s}s')
            result = self._out_q.get(timeout=remaining)
            if isinstance(result, WorkError):
                raise RuntimeError(f'ParallelCFRTrainer: worker {result.worker_id} raised:\n{result.traceback}')
            if not isinstance(result, WorkResult):
                raise TypeError(f'ParallelCFRTrainer: unexpected queue payload {type(result)!r}')
            all_batches.extend(result.batches)

        ingest_batches(
            all_batches,
            self.advantage_buffers,
            self.strategy_buffer,
            self.value_buffer,
            self.rng,
        )

    def shutdown(self) -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True

        while True:
            try:
                self._out_q.get_nowait()
            except queue_mod.Empty:
                break
        for q in self._in_qs:
            try:
                q.put(None, timeout=1.0)
            except queue_mod.Full:
                pass
            except Exception:
                pass

        for p in self._procs:
            p.join(timeout=10)
            if p.is_alive():
                p.terminate()
                p.join(timeout=5)
                if p.is_alive():
                    p.kill()
                    p.join(timeout=2)

        for q in self._in_qs:
            q.close()
            q.cancel_join_thread()
        self._out_q.close()
        self._out_q.cancel_join_thread()

    def __enter__(self) -> 'ParallelCFRTrainer':
        return self

    def __exit__(self, *args) -> None:
        self.shutdown()
