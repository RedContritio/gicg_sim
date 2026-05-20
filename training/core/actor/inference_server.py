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

Loopback fallback: ``forward_one`` does an in-proc forward (P3-A tests +
``InferenceClient`` with ``server=`` arg).
"""

from __future__ import annotations

import pickle
import queue as _queue
import time
import traceback
import warnings
from typing import Any

import torch

from training.core.actor._inference_helpers import (
    _AccelState,
    _from_bytes,
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
) -> None:
    """Top-level so it's picklable into spawn target.

    ``inference_acceleration``: ``'none'`` (raw) | ``'trace'`` (lazy
    first-batch jit.trace, invalidated on weight update) | ``'compile'``
    (torch.compile once at startup; weight updates do NOT invalidate).
    Trace/compile fall back to raw forward on failure.

    ``request_decoder_path``: empty = legacy decode (unpickle torch obs
    + tensor.to(device)). When set, dotted ``module.attr`` resolves to
    ``decoder(obs_bytes, mask_bytes, device, client_cache, network) ->
    (obs, mask)``. Per-client cache the decoder owns; server wipes on
    weight update. ``network`` exposed so decoder can reuse sub-modules.

    Response encoding: when ``request_decoder_path`` is set the server
    returns numpy bytes (torch tensor → ``detach().cpu().numpy()``) so
    the actor process unpickles without importing torch (I25 cutover —
    drops ~400 MB CUDA mmap RSS per actor). Legacy path keeps the
    pickled-torch-tensor response so existing tests + non-DMC callers
    are unchanged.
    """
    harden_child_env()
    install_quiet_sigterm(stop_event)
    trace.configure(role='inf_server', id=0)
    # PyTorch CUDA allocator 默认 caching 不释放,长跑后 InfServer RSS 飙
    # 到 25-35 GB(per 2026-05-20 production run 078 实测,~10 GB/h 涨)。
    # expandable_segments:True 让 allocator 用 vmem reservation 而非物理,
    # 不用时操作系统能 reclaim。Win + CUDA 12.x+ 支持。
    # max_split_size_mb 限单个 allocation 上限 → 减少碎片,小模型更友好。
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
    ready_event.set()
    timeout_s = batch_timeout_ms / 1000.0

    while not stop_event.is_set():
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
        # Paradigm-aware batched path: networks exposing batched_forward
        # + batch>1 → one forward + scatter via _run_batched_path. Singletons
        # + networks without batched_forward fall to the per-request loop
        # (only path that exercises trace/compile accel).
        if hasattr(network, 'batched_forward') and len(batch) > 1:
            with trace.span('inf_server.batched_forward'):
                _run_batched_path(
                    network,
                    batch,
                    device_str,
                    response_qs,
                    request_decoder,
                    shared_cache,
                    return_numpy=return_numpy,
                )
            continue

        for msg in batch:
            _kind, client_id, req_id, obs_bytes, mask_bytes = msg
            try:
                with trace.span('inf_server.decode'):
                    if request_decoder is not None:
                        obs, mask = request_decoder(obs_bytes, mask_bytes, device_str, shared_cache, network)
                    else:
                        # IPC delivers CPU tensors; move to server device.
                        # Response cast to cpu before pickling so client-side
                        # unpickle works on hosts without matching cuda.
                        obs = _from_bytes(obs_bytes)
                        mask = _from_bytes(mask_bytes) if mask_bytes is not None else None
                        obs = _to_device(obs, device_str)
                        if mask is not None:
                            mask = _to_device(mask, device_str)
                net = accel.select(obs, mask)
                with trace.span('inf_server.forward'):
                    with torch.inference_mode():
                        out = net(obs, mask) if mask is not None else net(obs)
                with trace.span('inf_server.dispatch'):
                    out = _to_device(out, 'cpu')
                    payload_bytes = _to_bytes_numpy(out) if return_numpy else _to_bytes(out)
                    response_qs[client_id].put(('ok', req_id, payload_bytes))
            except Exception as exc:
                response_qs[client_id].put(('err', req_id, f'{type(exc).__name__}: {exc}'))


class InferenceServer:
    """Spawn-ctx batched inference server. Workflow: construct →
    ``register_client(q)`` for each client → ``start()`` to spawn.
    ``inference_acceleration``: ``'none'`` | ``'trace'`` | ``'compile'``
    (see ``_server_loop``). ``use_jit_trace=True`` is a deprecated alias
    that converts to ``'trace'`` with a ``DeprecationWarning``."""

    def __init__(
        self,
        network: torch.nn.Module,
        device: str = 'cpu',
        max_batch: int = 64,
        batch_timeout_ms: int = 2,
        inference_acceleration: str = 'none',
        use_jit_trace: bool = False,
        request_decoder_path: str = '',
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
        ctx = get_ctx()
        self.request_queue = ctx.Queue()
        self._ready_event = ctx.Event()
        self._stop_event = ctx.Event()
        self._response_qs: list = []
        self._proc = None

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
        if self._proc is None:
            return
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
