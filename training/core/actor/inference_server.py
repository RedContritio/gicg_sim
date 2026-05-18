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

from training.core.actor._mp_helpers import (
    get_ctx,
    harden_child_env,
    install_quiet_sigterm,
)

_VALID_ACCEL = ('none', 'trace', 'compile')


def _to_bytes(t: Any) -> bytes:
    return pickle.dumps(t, protocol=pickle.HIGHEST_PROTOCOL)


def _from_bytes(b: bytes) -> Any:
    return pickle.loads(b)


def _to_device(obj: Any, device: str) -> Any:
    """Recurse into dict / tuple / Tensor and `.to(device)` each tensor.

    obs may be a single tensor, a dict of tensors (DMC), or a tuple
    (legacy). Non-tensor leaf values pass through unchanged.
    """
    if isinstance(obj, torch.Tensor):
        return obj.to(device)
    if isinstance(obj, dict):
        return {k: _to_device(v, device) for k, v in obj.items()}
    if isinstance(obj, (tuple, list)):
        return type(obj)(_to_device(v, device) for v in obj)
    return obj


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
) -> None:
    """Top-level so it's picklable into spawn target.

    ``inference_acceleration``: ``'none'`` (raw) | ``'trace'`` (lazy
    first-batch jit.trace, invalidated on weight update) | ``'compile'``
    (torch.compile once after pickle.loads — weight updates do NOT
    invalidate since load_state_dict mutates in place). Trace + compile
    both fall back to raw forward on construction failure.
    """
    harden_child_env()
    install_quiet_sigterm(stop_event)
    try:
        network = pickle.loads(network_bytes).to(device_str).eval()
    except Exception as exc:  # pragma: no cover — startup failure surface
        ready_event.set()
        stop_event.set()
        raise RuntimeError(f'InferenceServer init failed: {exc}\n{traceback.format_exc()}')

    # Compile-once path: build before ready_event so the first forward
    # incurs no compile penalty.
    compiled_net: Any = None
    if inference_acceleration == 'compile':
        try:
            compiled_net = torch.compile(network, mode='reduce-overhead', dynamic=True)
        except Exception as exc:
            print(
                f'[InferenceServer] torch.compile failed ({type(exc).__name__}: {exc}); '
                f'falling back to raw forward for remainder of process lifetime.'
            )
            compiled_net = None

    # Lazy first-batch trace state — ``trace_attempted`` is one-shot
    # (success OR failure both block per-call retry).
    traced_net: Any = None
    trace_attempted = False

    def _maybe_trace(obs: Any, mask: Any):
        nonlocal traced_net, trace_attempted
        if trace_attempted:
            return traced_net if traced_net is not None else network
        trace_attempted = True
        try:
            example = (obs, mask) if mask is not None else (obs,)
            traced_net = torch.jit.trace(network, example, check_trace=False)
        except Exception as exc:
            print(
                f'[InferenceServer] torch.jit.trace failed ({type(exc).__name__}: {exc}); '
                f'falling back to untraced forward for remainder of process lifetime.'
            )
            traced_net = None
        return traced_net if traced_net is not None else network

    def _select_net(obs: Any, mask: Any):
        if inference_acceleration == 'compile':
            return compiled_net if compiled_net is not None else network
        if inference_acceleration == 'trace':
            return _maybe_trace(obs, mask)
        return network

    def _invalidate_trace() -> None:
        nonlocal traced_net, trace_attempted
        if inference_acceleration == 'trace':
            traced_net = None
            trace_attempted = False
        # compile mode: parameter tensors mutated in place; no invalidate.

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
                _invalidate_trace()
            except Exception as exc:  # pragma: no cover
                print(f'[InferenceServer] weight load failed: {exc}')
            continue
        batch.append(first)
        deadline = time.perf_counter() + timeout_s
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
                    _invalidate_trace()
                except Exception as exc:  # pragma: no cover
                    print(f'[InferenceServer] weight load failed: {exc}')
                continue
            batch.append(msg)
        # Per-request forward — paradigm-specific shapes prevent safe
        # uniform stacking. Batching gains left for a paradigm-aware hook.
        for msg in batch:
            _kind, client_id, req_id, obs_bytes, mask_bytes = msg
            try:
                obs = _from_bytes(obs_bytes)
                mask = _from_bytes(mask_bytes) if mask_bytes is not None else None
                # Move obs to server device — IPC delivers CPU-pickled
                # tensors; network may live on cuda. Mirror back to cpu
                # before pickling response so client-side unpickle works
                # on hosts without a matching cuda runtime.
                obs = _to_device(obs, device_str)
                if mask is not None:
                    mask = _to_device(mask, device_str)
                net = _select_net(obs, mask)
                with torch.inference_mode():
                    out = net(obs, mask) if mask is not None else net(obs)
                out = _to_device(out, 'cpu')
                response_qs[client_id].put(('ok', req_id, _to_bytes(out)))
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
        # cancel_join_thread before close: at shutdown the feeder thread
        # may be blocked on a pipe write whose reader (the spawned server
        # process) has died → join_thread would hang indefinitely. We do
        # not care about in-flight messages at shutdown, so drop them.
        try:
            self.request_queue.cancel_join_thread()
        except Exception:
            pass
        try:
            self.request_queue.close()
        except Exception:
            pass
        # Symmetric cleanup on per-client response queues; same deadlock
        # surfaces if any reply is in-flight when shutdown trips.
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
