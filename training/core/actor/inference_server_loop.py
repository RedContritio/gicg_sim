"""InferenceServer batched-forward loop — the spawn target.

Batching, the wire protocol (request_q msgs, response_qs replies) and the
loopback contract are documented on ``InferenceServer`` in
``inference_server.py``; this module holds only the child-side loop body,
split out so both modules stay within the 300-line source cap.
"""

from __future__ import annotations

import queue as _queue
import time
from typing import Optional

from training.core.actor._inference_helpers import _run_batched_path
from training.core.actor._mp_helpers import (
    harden_child_env,
    install_quiet_sigterm,
)
from training.core.actor.inference_server_child import _init_child_process
from training.core.actor.inference_server_forward import _run_singleton_path
from training.core.actor.inference_server_socket_forward import _start_socket_forwarding
from training.core.perf import trace


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
    network, request_decoder, return_numpy, shared_cache, accel = _init_child_process(
        network_bytes,
        device_str,
        inference_acceleration,
        request_decoder_path,
        ready_event,
        stop_event,
    )

    socket_listener_thr, socket_listener_stop = _start_socket_forwarding(
        socket_port,
        socket_max_actions,
        socket_payload_encoder_path,
        request_decoder,
        request_q,
        response_qs,
        ready_event,
        stop_event,
    )

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

        timing = _run_singleton_path(
            network,
            batch,
            device_str,
            response_qs,
            request_decoder,
            shared_cache,
            accel,
            return_numpy=return_numpy,
            measure=stats_enabled,
        )
        if stats_enabled:
            stats_sum_decode_ms += timing['decode_ms']
            stats_sum_forward_ms += timing['forward_ms']
            stats_sum_dispatch_ms += timing['dispatch_ms']
            _maybe_emit_stats()

    # Stop the optional socket listener before leaving the child process.
    if socket_listener_stop is not None:
        socket_listener_stop.set()
        if socket_listener_thr is not None and socket_listener_thr.is_alive():
            socket_listener_thr.join(timeout=2.0)
