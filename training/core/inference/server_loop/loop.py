"""Server-loop event loop + _ServerState."""

from __future__ import annotations

import multiprocessing as mp
import multiprocessing.connection as mp_conn
import time
import traceback
from typing import TYPE_CHECKING

from training.core.inference.server_loop.drain import (
    _drain_pipes,
    _drain_weight_queue,
    _process_batch,
)
from training.core.inference.server_loop.stats import (
    _flush_stats,
    _maybe_emit_stats,
)

if TYPE_CHECKING:
    from training.core.inference.server import InferenceServerConfig
    from training.core.network import AgentConfig


class _ServerState:
    """Per-process state: current weight version, accumulated batch
    stats since the last emit, timestamp of the last emit."""

    def __init__(self) -> None:
        self.weight_version: int = 0
        self.batches_since_emit: int = 0
        self.reqs_since_emit: int = 0
        self.eval_batches_since_emit: int = 0
        self.eval_reqs_since_emit: int = 0
        self.eval_batch_sizes: list[int] = []
        self.last_emit_t: float = time.perf_counter()


def _server_loop(
    agent_config: 'AgentConfig',
    server_cfg: 'InferenceServerConfig',
    worker_pipes: list[mp_conn.Connection],
    weight_queue: 'mp.Queue',
    stats_queue: 'mp.Queue',
    error_queue: 'mp.Queue',
    ready_event: 'mp.Event',
) -> None:
    """Child process entry."""
    try:
        import torch  # noqa: F401 — pay the import cost in child

        from training.paradigms.az.network import Agent

        agent = Agent(agent_config)
        agent.net.eval()

        cache: dict[tuple[int, int], dict] = {}
        state = _ServerState()
        timeout_s = server_cfg.batch_timeout_ms / 1000.0
        emit_interval = max(0.1, server_cfg.stats_emit_interval_s)

        ready_event.set()

        while True:
            stop = _drain_weight_queue(weight_queue, agent, state)
            if stop:
                _flush_stats(stats_queue, state, force=True)
                return

            ready_pipes = mp_conn.wait(worker_pipes, timeout=timeout_s)
            _maybe_emit_stats(stats_queue, state, emit_interval)
            if not ready_pipes:
                continue

            batch: list[tuple[dict, mp_conn.Connection]] = []
            _drain_pipes(ready_pipes, batch, server_cfg.max_batch_size)
            if len(batch) < server_cfg.max_batch_size:
                remaining = [p for p in worker_pipes if p not in ready_pipes]
                _drain_pipes(remaining, batch, server_cfg.max_batch_size)

            if not batch:
                continue

            _process_batch(agent, cache, batch, state)
            _maybe_emit_stats(stats_queue, state, emit_interval)

    except Exception as exc:
        error_queue.put(
            {
                'error': f'{type(exc).__name__}: {exc}',
                'traceback': traceback.format_exc(),
            }
        )
        raise
