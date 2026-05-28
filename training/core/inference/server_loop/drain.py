"""Pipe / weight-queue drains + dispatch into paradigm-supplied handlers。

W2-2 (post-2026-05-28):pre-W2 此模块直接实现了 ``_handle_game_start`` +
``_handle_eval_batch`` 两 handler,实现写死 AZ obs schema(15-tensor 解码 +
``out['policy']`` / ``out['value']`` + ``agent.encode_static_tensors_with_tokens``
6-tuple 约定)— audit finding 高优 #2,违反 "core algorithm-agnostic" 契约。

post-W2-2:本模块仅持 generic dispatch(``_process_batch`` 把 kind=game_start
/ game_end / eval 路由到对应 handler)+ 真 generic 的 game_end(纯
``cache.pop`` + ``pipe.send`` ack);paradigm-specific game_start + eval batch
handler 来自 ``InferenceHandlers`` dataclass,由 ``_server_loop`` 调
``actor_process.resolve_builder`` 从 module path 注入。
"""

from __future__ import annotations

import multiprocessing as mp
import multiprocessing.connection as mp_conn
import queue as queue_mod
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class InferenceHandlers:
    """Paradigm-supplied inference handlers,注入到 ``_process_batch``。

    AZ paradigm 通过 ``inference_handlers_module_path``(传给
    ``InferenceServer.__init__``)指向 ``training.paradigms.az._inference_handlers``,
    module 顶层暴露 ``handle_game_start`` + ``handle_eval_batch`` callable。
    """

    handle_game_start: Callable
    handle_eval_batch: Callable


def _drain_pipes(
    pipes,
    batch: list[tuple[dict, mp_conn.Connection]],
    max_batch: int,
) -> None:
    """Pull every immediately-available message off the given pipes
    into ``batch``, up to ``max_batch`` total entries. ``pipe.poll()``
    is non-blocking。"""
    for pipe in pipes:
        if len(batch) >= max_batch:
            return
        try:
            while pipe.poll():
                req = pipe.recv()
                batch.append((req, pipe))
                if len(batch) >= max_batch:
                    return
        except EOFError:
            continue


def _drain_weight_queue(
    weight_queue: 'mp.Queue',
    agent,
    state,
) -> bool:
    """Apply any pending weight updates. Returns True if a ``stop``
    command was seen。"""
    stop = False
    while True:
        try:
            msg = weight_queue.get_nowait()
        except queue_mod.Empty:
            return stop
        kind = msg['kind']
        if kind == 'stop':
            stop = True
        elif kind == 'weight_update':
            agent.net.load_state_dict(msg['weights'])
            state.weight_version += 1
        else:
            raise RuntimeError(f'weight_queue got unknown kind: {kind!r}')


def _process_batch(
    agent,
    cache: dict[tuple[int, int], dict],
    batch: list[tuple[dict, mp_conn.Connection]],
    state,
    handlers: InferenceHandlers,
) -> None:
    """Dispatch a batch by request kind。"""
    state.batches_since_emit += 1
    state.reqs_since_emit += len(batch)

    eval_entries: list[tuple[dict, mp_conn.Connection]] = []
    for req, pipe in batch:
        kind = req['kind']
        if kind == 'game_start':
            handlers.handle_game_start(agent, cache, req, pipe, state)
        elif kind == 'game_end':
            _handle_game_end(cache, req, pipe)
        elif kind == 'eval':
            eval_entries.append((req, pipe))
        else:
            raise RuntimeError(f'server got unknown request kind: {kind!r}')

    if eval_entries:
        state.eval_batches_since_emit += 1
        state.eval_reqs_since_emit += len(eval_entries)
        state.eval_batch_sizes.append(len(eval_entries))
        handlers.handle_eval_batch(agent, cache, eval_entries)


def _handle_game_end(cache, req, pipe) -> None:
    wid = int(req['worker_id'])
    gid = int(req['game_id'])
    cache.pop((wid, gid), None)
    pipe.send({'kind': 'game_end_ack'})
