"""Centralized NN inference server for parallel self-play.

The server runs in its own process. It holds ONE Agent (AZ for now)
and services batched evaluation requests from worker processes over
``multiprocessing.Pipe`` connections.

``InferenceClient`` defines the worker-side request sequence; this module
owns only the main-process handle and child-process lifecycle.
"""

from __future__ import annotations

import multiprocessing as mp
import multiprocessing.connection as mp_conn
import queue as queue_mod
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from training.core.network import AgentConfig


@dataclass
class InferenceServerConfig:
    """Parameters that tune the server loop. All knobs live here so
    the trainer config can forward them straight through."""

    max_batch_size: int = 32
    batch_timeout_ms: float = 3.0
    weight_queue_timeout_s: float = 0.001
    stats_emit_interval_s: float = 5.0


from training.core.inference.server_loop import _server_loop


class InferenceServer:
    """Main-process handle for the inference server process."""

    def __init__(
        self,
        agent_config: 'AgentConfig',
        n_workers: int,
        server_cfg: Optional[InferenceServerConfig] = None,
        *,
        network_factory_path: str = '',
        inference_handlers_module_path: str = '',
    ):
        if n_workers <= 0:
            raise ValueError(f'n_workers must be positive, got {n_workers}')
        if not network_factory_path:
            raise ValueError(
                'InferenceServer: network_factory_path is required; supply the dotted '
                'module.attr path for the paradigm network, e.g. AZ passes '
                "'training.paradigms.az.network.Agent')"
            )
        if not inference_handlers_module_path:
            raise ValueError(
                'InferenceServer: inference_handlers_module_path is required; point at '
                'a paradigm module exposing handle_game_start and handle_eval_batch, '
                "e.g. AZ passes 'training.paradigms.az._inference_handlers')"
            )
        self.agent_config = agent_config
        self.n_workers = n_workers
        self.server_cfg = server_cfg or InferenceServerConfig()
        self.network_factory_path = network_factory_path
        self.inference_handlers_module_path = inference_handlers_module_path

        self._ctx = mp.get_context('spawn')
        self._worker_pipes_server_side: list[mp_conn.Connection] = []
        self._worker_pipes_client_side: list[mp_conn.Connection] = []
        for _ in range(n_workers):
            server_end, client_end = self._ctx.Pipe(duplex=True)
            self._worker_pipes_server_side.append(server_end)
            self._worker_pipes_client_side.append(client_end)

        self._weight_queue: 'mp.Queue' = self._ctx.Queue()
        self._stats_queue: 'mp.Queue' = self._ctx.Queue()
        self._error_queue: 'mp.Queue' = self._ctx.Queue()
        self._ready_event = self._ctx.Event()
        self._process: Optional[mp.Process] = None
        self._started = False

    @property
    def stats_queue(self) -> 'mp.Queue':
        return self._stats_queue

    def start(self, wait_ready_s: float = 15.0) -> None:
        if self._started:
            raise RuntimeError('InferenceServer already started')
        self._process = self._ctx.Process(
            target=_server_loop,
            args=(
                self.agent_config,
                self.server_cfg,
                self._worker_pipes_server_side,
                self._weight_queue,
                self._stats_queue,
                self._error_queue,
                self._ready_event,
                self.network_factory_path,
                self.inference_handlers_module_path,
            ),
            daemon=False,
        )
        self._process.start()
        for p in self._worker_pipes_server_side:
            p.close()
        self._started = True

        if not self._ready_event.wait(timeout=wait_ready_s):
            self._raise_if_error()
            raise TimeoutError(f'InferenceServer did not become ready within {wait_ready_s}s')

    def get_worker_pipe(self, worker_id: int) -> mp_conn.Connection:
        if not 0 <= worker_id < self.n_workers:
            raise IndexError(f'worker_id {worker_id} out of range')
        return self._worker_pipes_client_side[worker_id]

    def push_weights(self, cpu_state_dict: dict) -> None:
        if not self._started:
            raise RuntimeError('InferenceServer not started')
        self._weight_queue.put({'kind': 'weight_update', 'weights': cpu_state_dict})

    def _raise_if_error(self) -> None:
        try:
            err = self._error_queue.get_nowait()
        except queue_mod.Empty:
            return
        raise RuntimeError(f'InferenceServer crashed: {err["error"]}\n{err.get("traceback", "")}')

    def stop(self, wait_timeout_s: float = 10.0) -> None:
        if not self._started:
            return
        try:
            self._weight_queue.put({'kind': 'stop'}, timeout=1.0)
        except queue_mod.Full:
            pass
        t0 = time.perf_counter()
        self._process.join(
            timeout=max(0.1, wait_timeout_s - (time.perf_counter() - t0)),
        )
        if self._process.is_alive():
            self._process.terminate()
            self._process.join(timeout=1.0)
        self._started = False

        for p in self._worker_pipes_client_side:
            try:
                p.close()
            except Exception:
                pass
        self._worker_pipes_client_side.clear()

        self._raise_if_error()
