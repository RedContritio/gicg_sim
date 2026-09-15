"""TCP socket listener bridge for the ``InferenceServer`` child process.

Owns the ``socket_port > 0`` branch of the server loop: it validates the
Route A preconditions, resolves the paradigm's request encoder, and starts
a listener thread whose ``forward_cb`` pushes Go-actor requests onto the
same request queue the multiprocessing clients use — so socket requests go
through the identical batching / forward / response path.

Split out of ``inference_server.py`` so each module stays within the
300-line source cap; the public ``InferenceServer`` handle stays in
``inference_server.py``.
"""

from __future__ import annotations

import queue as _queue

from training.core.actor._inference_helpers import _from_bytes


def _start_socket_forwarding(
    socket_port: int,
    socket_max_actions: int,
    socket_payload_encoder_path: str,
    request_decoder,
    request_q,
    response_qs: list,
    ready_event,
    stop_event,
):
    """Start the optional socket listener; returns ``(None, None)`` when port <= 0.

    Route A (Go actors over TCP) needs a bounded action space and a request
    decoder, so both are validated here; a violation sets the ready + stop
    events before raising, matching the inline checks the loop used to carry.
    ``ready_event`` gates the bind — a listener that cannot bind raises a
    ``RuntimeError`` rather than leaving the parent waiting.

    Returns ``(listener_thread, listener_stop_event)``; the caller sets the
    stop event and joins the thread on shutdown.
    """
    # An optional socket listener adapts Go requests into the same request
    # queue and batched-forward loop used by multiprocessing clients.
    if socket_port <= 0:
        return None, None
    if socket_max_actions <= 0 or request_decoder is None:
        ready_event.set()
        stop_event.set()
        raise RuntimeError(
            '_server_loop: socket_port > 0 (Route A) requires socket_max_actions > 0 and request_decoder_path set'
        )
    if not socket_payload_encoder_path:
        ready_event.set()
        stop_event.set()
        raise RuntimeError(
            '_server_loop: socket_port > 0 requires socket_payload_encoder_path to name the paradigm request encoder'
        )
    from training.core.actor.actor_process import resolve_builder as _resolve_builder
    from training.core.actor.inference_server_socket_listener import (
        start_listener_in_thread as _start_socket_listener,
    )
    from training.core.actor.inference_server_socket_wire import (
        INFER_STATUS_ERR,
        INFER_STATUS_OK,
        InferRequest as _SocketInferRequest,
        InferResponse as _SocketInferResponse,
    )
    import numpy as _np
    import sys as _sys
    import threading as _threading

    socket_request_to_pickled_payload = _resolve_builder(socket_payload_encoder_path)

    def forward_cb(req: '_SocketInferRequest') -> '_SocketInferResponse':
        """Route one socket request through the shared batch queue."""
        cid = req.client_id
        # A Go actor id must address a pre-registered response queue.
        if cid < 0 or cid >= len(response_qs):
            raise ValueError(
                f'socket forward: client_id {cid} 越界 [0,{len(response_qs)}) — socket_clients 与 Go actor 数不一致'
            )
        obs_bytes = socket_request_to_pickled_payload(req, max_actions=socket_max_actions)
        request_q.put(('infer', cid, req.req_id, obs_bytes, b''))
        # Poll with a timeout so shutdown cannot strand this handler.
        # Discard stale responses until the matching request id arrives.
        while not stop_event.is_set():
            try:
                kind, rid, payload = response_qs[cid].get(timeout=0.5)
            except _queue.Empty:
                continue
            if rid != req.req_id:
                print(
                    f'[InferenceServer] socket forward 丢弃 stale 响应 client={cid} got req_id={rid} want={req.req_id}',
                    file=_sys.stderr,
                    flush=True,
                )
                continue
            if kind == 'ok':
                arr = _from_bytes(payload)
                logits = _np.asarray(arr, dtype=_np.float32).ravel()
                return _SocketInferResponse(status=INFER_STATUS_OK, logits=logits)
            if kind == 'err':
                return _SocketInferResponse(status=INFER_STATUS_ERR, err_msg=str(payload))
            raise ValueError(f'socket forward: 未知 response kind {kind!r}')
        # Return a protocol error when shutdown interrupts the request.
        return _SocketInferResponse(status=INFER_STATUS_ERR, err_msg='inference server stopping')

    socket_listener_ready = _threading.Event()
    socket_listener_stop = _threading.Event()
    socket_listener_thr = _start_socket_listener(socket_port, forward_cb, socket_listener_ready, socket_listener_stop)
    if not socket_listener_ready.wait(timeout=5.0):
        stop_event.set()
        raise RuntimeError(f'InferenceServer socket listener bind timeout on port {socket_port}')

    return socket_listener_thr, socket_listener_stop
