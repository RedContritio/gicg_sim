"""Worker-side client for the inference server.

Lives inside a worker process, holds one ``multiprocessing.Pipe``
client-end to the server, and implements the same "evaluator"
protocol ``training.paradigms.az.network.Agent`` exposes:

    evaluator.game_start(static_obs_np) -> game_static dict
    evaluator.eval_state(dyn_obs_np, refs_np, payments_np) -> (prior, value)
    evaluator.game_end() -> None

This lets ``play_self_game`` / MCTS use the same call pattern for
both the in-process Agent (arena / gauntlet) and the remote
inference client (parallel self-play workers).
"""

from __future__ import annotations

from typing import Any

import numpy as np


class InferenceClient:
    """One instance per worker. Not thread-safe; the worker's MCTS
    loop is single-threaded and hits this synchronously."""

    def __init__(self, worker_id: int, pipe):
        self.worker_id = int(worker_id)
        self._pipe = pipe
        self._current_game_id: int = -1
        self._next_game_id: int = 0
        self._current_weight_version: int = -1

    @property
    def current_weight_version(self) -> int:
        return self._current_weight_version

    # --- Evaluator protocol ----------------------------------------- #

    def game_start(self, static_obs_np: np.ndarray) -> dict:
        gid = self._next_game_id
        self._next_game_id += 1
        self._current_game_id = gid

        self._pipe.send(
            {
                'kind': 'game_start',
                'worker_id': self.worker_id,
                'game_id': gid,
                'static_obs': np.ascontiguousarray(static_obs_np),
            }
        )
        resp = self._pipe.recv()
        if resp['kind'] != 'game_start_ack':
            raise RuntimeError(f'InferenceClient.game_start: expected game_start_ack, got {resp["kind"]}')
        self._current_weight_version = int(resp.get('weight_version', -1))
        return resp['game_static']

    def eval_state(
        self,
        dyn_obs_np: np.ndarray,
        refs_np: np.ndarray,
        payments_np: np.ndarray,
    ) -> tuple[np.ndarray, float]:
        self.send_eval(dyn_obs_np, refs_np, payments_np)
        return self.recv_eval()

    # --- Async eval ------------------------------------------------- #

    def send_eval(
        self,
        dyn_obs_np: np.ndarray,
        refs_np: np.ndarray,
        payments_np: np.ndarray,
    ) -> None:
        if self._current_game_id < 0:
            raise RuntimeError(
                'InferenceClient.send_eval called before game_start — call game_start at the start of each game'
            )
        self._pipe.send(
            {
                'kind': 'eval',
                'worker_id': self.worker_id,
                'game_id': self._current_game_id,
                'dyn': np.ascontiguousarray(dyn_obs_np),
                'refs': np.ascontiguousarray(refs_np),
                'payments': np.ascontiguousarray(payments_np),
            }
        )

    def recv_eval(self) -> tuple[np.ndarray, float]:
        resp = self._pipe.recv()
        if resp['kind'] != 'eval_ack':
            raise RuntimeError(f'InferenceClient.recv_eval: expected eval_ack, got {resp["kind"]}')
        return resp['prior'], resp['value']

    def game_end(self) -> None:
        if self._current_game_id < 0:
            return
        gid = self._current_game_id
        self._current_game_id = -1
        self._pipe.send(
            {
                'kind': 'game_end',
                'worker_id': self.worker_id,
                'game_id': gid,
            }
        )
        resp = self._pipe.recv()
        if resp['kind'] != 'game_end_ack':
            raise RuntimeError(f'InferenceClient.game_end: expected game_end_ack, got {resp["kind"]}')
