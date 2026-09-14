"""InferenceServer — batched-forward server in a dedicated mp.Process.

Wire protocol (request_q msgs):

    ('infer', client_id:int, request_id:str, obs_bytes:bytes, mask_bytes:bytes|None)
    ('weights', state_dict:dict)
    ('stop',)

Server batches up to ``max_batch`` infer requests (or until
``batch_timeout_ms`` since the batch's first request), forwards on
``device``, replies on the response queue registered for ``client_id``
with ``('ok', request_id, logits_bytes)`` or ``('err', ..., repr(exc))``.
Response queues MUST be registered before ``start()`` because
``mp.Queue`` cannot traverse another queue — it crosses spawn as an arg.

Loopback fallback: ``forward_one`` performs an in-process forward for tests
and ``InferenceClient(server=...)`` callers.
"""

from __future__ import annotations

import pickle
import queue as _queue
import time
import traceback
import warnings
from typing import Any, Optional

import torch

from training.core.actor._inference_helpers import (
    _AccelState,
    _from_bytes,
    _infer_stream_ctx,
    _run_batched_path,
    _to_bytes,
    _to_bytes_numpy,
    _to_device,
)
from training.core.actor._mp_helpers import (
    get_ctx,
    harden_child_env,
    install_quiet_sigterm,
)
from training.core.perf import trace

_VALID_ACCEL = ('none', 'trace', 'compile')


def _server_loop(
    network_bytes: bytes,
    device_str: str,
    max_batch: int,
    batch_timeout_ms: int,
    request_q,
    response_qs: list,
    ready_event,
    stop_event,
    inference_acceleration: str = 'none',
    request_decoder_path: str = '',
    socket_payload_encoder_path: str = '',
    stats_q=None,
    stats_interval_s: float = 5.0,
    socket_port: int = 0,
    socket_max_actions: int = 0,
    perf_trace_enabled: bool = False,
    perf_trace_flush_n: int = 200,
    perf_trace_flush_s: float = 1.0,
    perf_trace_dir: Optional[str] = None,
) -> None:
    """Top-level so it's picklable into spawn target.

    ``inference_acceleration``: ``'none'`` (raw) | ``'trace'`` (lazy
    first-batch jit.trace, invalidated on weight update) | ``'compile'``
    (torch.compile once at startup; weight updates do NOT invalidate).
    Trace/compile fall back to raw forward on failure.

    ``request_decoder_path``: empty uses the generic decode path (unpickle Torch obs
    + tensor.to(device)). When set, dotted ``module.attr`` resolves to
    ``decoder(obs_bytes, mask_bytes, device, client_cache, network) ->
    (obs, mask)``. Per-client cache the decoder owns; server wipes on
    weight update. ``network`` exposed so decoder can reuse sub-modules.

    Response encoding: when ``request_decoder_path`` is set the server
    returns NumPy bytes (Torch tensor → ``detach().cpu().numpy()``) so
    the actor can unpickle without importing Torch. The generic path keeps
    the pickled-Torch-tensor response.
    """
    harden_child_env()
    install_quiet_sigterm(stop_event)
    # The parent passes explicit tracing settings across the spawn boundary.
    if perf_trace_enabled:
        trace.enable_explicit(
            flush_window=perf_trace_flush_n,
            flush_interval_s=perf_trace_flush_s,
            log_dir=perf_trace_dir,
        )
    trace.configure(role='inf_server', id=0)
    # Prefer expandable CUDA allocator segments and bounded split sizes to
    # reduce long-running fragmentation.
    import os as _os

    _os.environ.setdefault(
        'PYTORCH_CUDA_ALLOC_CONF',
        'expandable_segments:True,max_split_size_mb:128',
    )
    try:
        network = pickle.loads(network_bytes).to(device_str).eval()
    except Exception as exc:  # pragma: no cover — startup failure surface
        ready_event.set()
        stop_event.set()
        raise RuntimeError(f'InferenceServer init failed: {exc}\n{traceback.format_exc()}')

    request_decoder = None
    # Decoder-path implies actor stays torch-free → response must be
    # numpy bytes. Legacy callers (test nets, AZ-loopback fallback)
    # keep the pickled torch tensor response.
    return_numpy = bool(request_decoder_path)
    if request_decoder_path:
        from training.core.actor.actor_process import resolve_builder

        request_decoder = resolve_builder(request_decoder_path)
    # Server-wide decoder cache (shared across all clients). Decoder
    # internally keys by static_obs hash so multiple actors sharing the
    # same scenario hit the same cache entry — for fixed-scenario DMC,
    # this means hook_encoder runs **once total**, not once per
    # actor×episode. Server wipes on weight update.
    shared_cache: dict = {}

    # _AccelState builds compile-once net up-front + lazy-traces on first
    # request when mode='trace'; both failures fall back to raw forward.
    accel = _AccelState(network, inference_acceleration)

    # An optional socket listener adapts Go requests into the same request
    # queue and batched-forward loop used by multiprocessing clients.
    socket_listener_thr = None
    socket_listener_stop = None
    if socket_port > 0:
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
                '_server_loop: socket_port > 0 requires socket_payload_encoder_path '
                'to name the paradigm request encoder'
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
                        f'[InferenceServer] socket forward 丢弃 stale 响应 client={cid} '
                        f'got req_id={rid} want={req.req_id}',
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
        socket_listener_thr = _start_socket_listener(
            socket_port, forward_cb, socket_listener_ready, socket_listener_stop
        )
        if not socket_listener_ready.wait(timeout=5.0):
            stop_event.set()
            raise RuntimeError(f'InferenceServer socket listener bind timeout on port {socket_port}')

    ready_event.set()
    timeout_s = batch_timeout_ms / 1000.0

    # Aggregate interval counters only when a stats queue is configured.
    stats_enabled = stats_q is not None and stats_interval_s > 0
    stats_n_batches = 0
    stats_n_requests = 0
    stats_sum_batch_size = 0
    stats_max_batch_size = 0
    stats_sum_qsize = 0
    stats_max_qsize = 0
    stats_qsize_samples = 0
    stats_sum_decode_ms = 0.0
    stats_sum_forward_ms = 0.0
    stats_sum_dispatch_ms = 0.0
    stats_sum_fillwait_ms = 0.0
    stats_t_last_emit = time.perf_counter()

    def _maybe_emit_stats():
        nonlocal stats_n_batches, stats_n_requests, stats_sum_batch_size, stats_max_batch_size
        nonlocal stats_sum_qsize, stats_max_qsize, stats_qsize_samples
        nonlocal stats_sum_decode_ms, stats_sum_forward_ms, stats_sum_dispatch_ms, stats_sum_fillwait_ms
        nonlocal stats_t_last_emit
        if not stats_enabled:
            return
        now = time.perf_counter()
        elapsed = now - stats_t_last_emit
        if elapsed < stats_interval_s:
            return
        batches = max(1, stats_n_batches)
        qs_samples = max(1, stats_qsize_samples)
        payload = {
            'n_batches': stats_n_batches,
            'n_requests': stats_n_requests,
            'batch_size_avg': round(stats_sum_batch_size / batches, 2) if stats_n_batches else 0.0,
            'batch_size_max': stats_max_batch_size,
            'max_batch_cfg': max_batch,
            'batching_efficiency': round(stats_sum_batch_size / (batches * max_batch), 3) if stats_n_batches else 0.0,
            'queue_depth_avg': round(stats_sum_qsize / qs_samples, 2),
            'queue_depth_max': stats_max_qsize,
            'decode_ms_avg': round(stats_sum_decode_ms / batches, 3) if stats_n_batches else 0.0,
            'forward_ms_avg': round(stats_sum_forward_ms / batches, 3) if stats_n_batches else 0.0,
            'dispatch_ms_avg': round(stats_sum_dispatch_ms / batches, 3) if stats_n_batches else 0.0,
            'process_ms_avg': round((stats_sum_decode_ms + stats_sum_forward_ms + stats_sum_dispatch_ms) / batches, 3)
            if stats_n_batches
            else 0.0,
            'fillwait_ms_avg': round(stats_sum_fillwait_ms / batches, 3) if stats_n_batches else 0.0,
            'batches_per_sec': round(stats_n_batches / elapsed, 2),
            'requests_per_sec': round(stats_n_requests / elapsed, 2),
            'window_s': round(elapsed, 3),
        }
        try:
            stats_q.put_nowait(('inf_server', payload))
        except Exception:  # noqa: BLE001 — full queue or pipe broken;sampler must never kill server
            pass
        # Reset.
        stats_n_batches = 0
        stats_n_requests = 0
        stats_sum_batch_size = 0
        stats_max_batch_size = 0
        stats_sum_qsize = 0
        stats_max_qsize = 0
        stats_qsize_samples = 0
        stats_sum_decode_ms = 0.0
        stats_sum_forward_ms = 0.0
        stats_sum_dispatch_ms = 0.0
        stats_sum_fillwait_ms = 0.0
        stats_t_last_emit = now

    def _try_qsize() -> int:
        try:
            return request_q.qsize()
        except (NotImplementedError, AttributeError):
            return 0

    while not stop_event.is_set():
        if stats_enabled:
            qs = _try_qsize()
            stats_sum_qsize += qs
            stats_max_qsize = max(stats_max_qsize, qs)
            stats_qsize_samples += 1
        batch = []
        try:
            first = request_q.get(timeout=0.1)
        except _queue.Empty:
            continue
        if first[0] == 'stop':
            break
        if first[0] == 'weights':
            try:
                network.load_state_dict(first[1])
                accel.invalidate_trace()
                shared_cache.clear()
            except Exception as exc:  # pragma: no cover
                print(f'[InferenceServer] weight load failed: {exc}')
            continue
        batch.append(first)
        deadline = time.perf_counter() + timeout_s
        t_fillwait_start = time.perf_counter() if stats_enabled else 0.0
        with trace.span('inf_server.fill_wait'):
            while len(batch) < max_batch:
                remaining = deadline - time.perf_counter()
                if remaining <= 0:
                    break
                try:
                    msg = request_q.get(timeout=remaining)
                except _queue.Empty:
                    break
                if msg[0] == 'stop':
                    stop_event.set()
                    break
                if msg[0] == 'weights':
                    try:
                        network.load_state_dict(msg[1])
                        accel.invalidate_trace()
                        shared_cache.clear()
                    except Exception as exc:  # pragma: no cover
                        print(f'[InferenceServer] weight load failed: {exc}')
                    continue
                batch.append(msg)
        trace.value('inf_server.batch_size', float(len(batch)))
        if stats_enabled:
            stats_n_batches += 1
            stats_n_requests += len(batch)
            stats_sum_batch_size += len(batch)
            stats_max_batch_size = max(stats_max_batch_size, len(batch))
            stats_sum_fillwait_ms += (time.perf_counter() - t_fillwait_start) * 1000.0
        # Paradigm-aware batched path: networks exposing batched_forward
        # + batch>1 → one forward + scatter via _run_batched_path. Singletons
        # + networks without batched_forward fall to the per-request loop
        # (only path that exercises trace/compile accel).
        if hasattr(network, 'batched_forward') and len(batch) > 1:
            with trace.span('inf_server.batched_forward'):
                timing = _run_batched_path(
                    network,
                    batch,
                    device_str,
                    response_qs,
                    request_decoder,
                    shared_cache,
                    return_numpy=return_numpy,
                )
            if stats_enabled and timing:
                stats_sum_decode_ms += timing.get('decode_ms', 0.0)
                stats_sum_forward_ms += timing.get('forward_ms', 0.0)
                stats_sum_dispatch_ms += timing.get('dispatch_ms', 0.0)
                _maybe_emit_stats()
            continue

        for msg in batch:
            _kind, client_id, req_id, obs_bytes, mask_bytes = msg
            tt0 = time.perf_counter() if stats_enabled else 0.0
            try:
                with trace.span('inf_server.decode'):
                    if request_decoder is not None:
                        obs, mask = request_decoder(obs_bytes, mask_bytes, device_str, shared_cache, network)
                    else:
                        obs = _from_bytes(obs_bytes)
                        mask = _from_bytes(mask_bytes) if mask_bytes is not None else None
                        obs = _to_device(obs, device_str)
                        if mask is not None:
                            mask = _to_device(mask, device_str)
                tt1 = time.perf_counter() if stats_enabled else 0.0
                net = accel.select(obs, mask)
                with trace.span('inf_server.forward'), _infer_stream_ctx(device_str):
                    with torch.inference_mode():
                        out = net(obs, mask) if mask is not None else net(obs)
                    if stats_enabled and device_str.startswith('cuda'):
                        # Synchronize before the forward timer ends so host
                        # transfer is accounted for in dispatch.
                        torch.cuda.synchronize()
                tt2 = time.perf_counter() if stats_enabled else 0.0
                with trace.span('inf_server.dispatch'):
                    out = _to_device(out, 'cpu')
                    payload_bytes = _to_bytes_numpy(out) if return_numpy else _to_bytes(out)
                    response_qs[client_id].put(('ok', req_id, payload_bytes))
                if stats_enabled:
                    tt3 = time.perf_counter()
                    stats_sum_decode_ms += (tt1 - tt0) * 1000.0
                    stats_sum_forward_ms += (tt2 - tt1) * 1000.0
                    stats_sum_dispatch_ms += (tt3 - tt2) * 1000.0
            except Exception as exc:
                response_qs[client_id].put(('err', req_id, f'{type(exc).__name__}: {exc}'))
        if stats_enabled:
            _maybe_emit_stats()

    # Stop the optional socket listener before leaving the child process.
    if socket_listener_stop is not None:
        socket_listener_stop.set()
        if socket_listener_thr is not None and socket_listener_thr.is_alive():
            socket_listener_thr.join(timeout=2.0)


class InferenceServer:
    """Spawn-ctx batched inference server. Workflow: construct →
    ``register_client(q)`` for each client → ``start()`` to spawn.
    ``inference_acceleration``: ``'none'`` | ``'trace'`` | ``'compile'``
    (see ``_server_loop``). ``use_jit_trace=True`` is a deprecated alias
    that converts to ``'trace'`` with a ``DeprecationWarning``.

    Python clients use multiprocessing queues. When ``socket_port`` is
    positive, Go actors can also connect through TCP; socket requests enter
    the same batching queue.
    """

    def __init__(
        self,
        network: torch.nn.Module,
        device: str = 'cpu',
        max_batch: int = 64,
        batch_timeout_ms: int = 2,
        inference_acceleration: str = 'none',
        use_jit_trace: bool = False,
        request_decoder_path: str = '',
        socket_payload_encoder_path: str = '',
        stats_q=None,
        stats_interval_s: float = 5.0,
        socket_port: int = 0,
        socket_max_actions: int = 0,
        socket_clients: int = 0,
        perf_trace_enabled: bool = False,
        perf_trace_flush_n: int = 200,
        perf_trace_flush_s: float = 1.0,
        perf_trace_dir: Optional[str] = None,
    ) -> None:
        if use_jit_trace:
            if inference_acceleration != 'none':
                raise ValueError(
                    'InferenceServer: cannot pass both use_jit_trace=True and '
                    f'inference_acceleration={inference_acceleration!r}; '
                    "use inference_acceleration='trace' only."
                )
            warnings.warn(
                "InferenceServer: use_jit_trace=True is deprecated, use inference_acceleration='trace' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            inference_acceleration = 'trace'
        if inference_acceleration not in _VALID_ACCEL:
            raise ValueError(
                f'InferenceServer: inference_acceleration must be one of '
                f'{list(_VALID_ACCEL)}, got {inference_acceleration!r}'
            )
        self.network = network.to(device).eval()
        self.device = torch.device(device)
        self.max_batch = max_batch
        self.batch_timeout_ms = batch_timeout_ms
        self.inference_acceleration = inference_acceleration
        self.request_decoder_path = request_decoder_path
        self.socket_payload_encoder_path = socket_payload_encoder_path
        self.stats_q = stats_q
        self.stats_interval_s = stats_interval_s
        self.socket_port = int(socket_port)
        self.socket_max_actions = int(socket_max_actions)
        self.socket_clients = int(socket_clients)
        # Keep tracing settings explicit and spawn-picklable.
        self.perf_trace_enabled = bool(perf_trace_enabled)
        self.perf_trace_flush_n = int(perf_trace_flush_n)
        self.perf_trace_flush_s = float(perf_trace_flush_s)
        self.perf_trace_dir = perf_trace_dir
        ctx = get_ctx()
        self.request_queue = ctx.Queue()
        self._ready_event = ctx.Event()
        self._stop_event = ctx.Event()
        self._response_qs: list = []
        self._proc = None
        # Pre-register response queues indexed by Go actor id.
        for _ in range(self.socket_clients):
            self.register_client(ctx.Queue())

    @property
    def use_jit_trace(self) -> bool:
        """Back-compat read accessor for the deprecated boolean field."""
        return self.inference_acceleration == 'trace'

    def register_client(self, response_q) -> int:
        """Register a response queue (returns client_id). MUST run before
        ``start()`` so the queue traverses the spawn boundary."""
        if self._proc is not None:
            raise RuntimeError('InferenceServer.register_client: must register before start()')
        client_id = len(self._response_qs)
        self._response_qs.append(response_q)
        return client_id

    def start(self, wait_ready_s: float = 15.0) -> None:
        """Spawn the server process. Idempotent — calling twice raises."""
        if self._proc is not None:
            raise RuntimeError('InferenceServer.start: already started')
        ctx = get_ctx()
        net_bytes = pickle.dumps(self.network, protocol=pickle.HIGHEST_PROTOCOL)
        self._proc = ctx.Process(
            target=_server_loop,
            args=(
                net_bytes,
                str(self.device),
                self.max_batch,
                self.batch_timeout_ms,
                self.request_queue,
                self._response_qs,
                self._ready_event,
                self._stop_event,
                self.inference_acceleration,
                self.request_decoder_path,
                self.socket_payload_encoder_path,
                self.stats_q,
                self.stats_interval_s,
                self.socket_port,
                self.socket_max_actions,
                self.perf_trace_enabled,
                self.perf_trace_flush_n,
                self.perf_trace_flush_s,
                self.perf_trace_dir,
            ),
            daemon=False,
            name='InferenceServer',
        )
        self._proc.start()
        if not self._ready_event.wait(timeout=wait_ready_s):
            self.stop()
            raise TimeoutError(f'InferenceServer ready signal missed within {wait_ready_s}s')

    def forward_one(self, obs: Any, mask: Any) -> Any:
        """In-proc forward (loopback path for tests)."""
        with torch.inference_mode():
            return self.network(obs, mask) if mask is not None else self.network(obs)

    def update_network(self, state_dict: dict) -> None:
        """In-proc → load directly; spawned → push via request queue."""
        if self._proc is None:
            self.network.load_state_dict(state_dict)
        else:
            self.request_queue.put(('weights', state_dict))

    def stop(self, timeout_s: float = 5.0) -> None:
        self._stop_event.set()
        if self._proc is not None:
            try:
                self.request_queue.put(('stop',), timeout=1.0)
            except Exception:
                pass
            self._proc.join(timeout=timeout_s)
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(timeout=2.0)
            self._proc = None
        # cancel_join_thread before close: feeder thread can block on a
        # pipe write whose reader (dead server) hangs join_thread forever.
        # In-flight messages at shutdown are dropped intentionally.
        try:
            self.request_queue.cancel_join_thread()
        except Exception:
            pass
        try:
            self.request_queue.close()
        except Exception:
            pass
        # Symmetric cleanup on response queues — same deadlock surface.
        for q in self._response_qs:
            try:
                q.cancel_join_thread()
            except Exception:
                pass
            try:
                q.close()
            except Exception:
                pass

    def device_str(self) -> str:
        return str(self.device)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.is_alive()
