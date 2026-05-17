"""InferenceServer — batched-forward server in a dedicated mp.Process.

Wire protocol over an ``mp.Queue`` (request_q):

    ('infer', client_id:int, request_id:str, obs_bytes:bytes, mask_bytes:bytes|None)
    ('weights', state_dict:dict)
    ('stop',)

Server batches up to ``max_batch`` infer requests (or until
``batch_timeout_ms`` elapses since the first request in a batch),
forwards on ``device``, and replies on the pre-registered response
queue for ``client_id`` with ``('ok', request_id, logits_bytes)`` or
``('err', request_id, repr(exc))``.

Response queues must be registered before ``start()`` via
``register_client()`` because ``mp.Queue`` cannot be passed *through*
another queue — it must traverse the spawn boundary as an argument.

Loopback fallback: ``forward_one`` does an in-proc forward (used by
serial-mode tests + ``InferenceClient`` constructed with ``server=`` arg
directly). When the dedicated process is started via ``start()``, the
in-proc network handle is still kept for ``forward_one`` to keep
backward compatibility with P3-A loopback tests.
"""

from __future__ import annotations

import pickle
import queue as _queue
import time
import traceback
from typing import Any

import torch

from training.core.actor._mp_helpers import (
    get_ctx,
    harden_child_env,
    install_quiet_sigterm,
)


def _to_bytes(t: Any) -> bytes:
    return pickle.dumps(t, protocol=pickle.HIGHEST_PROTOCOL)


def _from_bytes(b: bytes) -> Any:
    return pickle.loads(b)


def _server_loop(
    network_bytes: bytes,
    device_str: str,
    max_batch: int,
    batch_timeout_ms: int,
    request_q,
    response_qs: list,
    ready_event,
    stop_event,
) -> None:
    """Top-level so it's picklable into spawn target."""
    harden_child_env()
    install_quiet_sigterm(stop_event)
    try:
        network = pickle.loads(network_bytes).to(device_str).eval()
    except Exception as exc:  # pragma: no cover — startup failure surface
        ready_event.set()
        stop_event.set()
        raise RuntimeError(f'InferenceServer init failed: {exc}\n{traceback.format_exc()}')
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
                except Exception as exc:  # pragma: no cover
                    print(f'[InferenceServer] weight load failed: {exc}')
                continue
            batch.append(msg)
        # Per-request forward — paradigm-specific shapes prevent safe
        # uniform stacking. Correctness preserved; batching gains are
        # left for a future paradigm-aware hook.
        for msg in batch:
            _kind, client_id, req_id, obs_bytes, mask_bytes = msg
            try:
                obs = _from_bytes(obs_bytes)
                mask = _from_bytes(mask_bytes) if mask_bytes is not None else None
                with torch.inference_mode():
                    out = network(obs, mask) if mask is not None else network(obs)
                response_qs[client_id].put(('ok', req_id, _to_bytes(out)))
            except Exception as exc:
                response_qs[client_id].put(('err', req_id, f'{type(exc).__name__}: {exc}'))


class InferenceServer:
    """Spawn-ctx batched inference server. Optional dedicated process.

    Workflow:

    1. Construct.
    2. ``register_client(q)`` for each client (returns client_id).
    3. ``start()`` to spawn dedicated process.
    4. Clients submit via ``request_queue`` keyed by their client_id;
       server replies on the pre-registered response queue.
    """

    def __init__(
        self,
        network: torch.nn.Module,
        device: str = 'cpu',
        max_batch: int = 64,
        batch_timeout_ms: int = 2,
    ) -> None:
        self.network = network.to(device).eval()
        self.device = torch.device(device)
        self.max_batch = max_batch
        self.batch_timeout_ms = batch_timeout_ms
        ctx = get_ctx()
        self.request_queue = ctx.Queue()
        self._ready_event = ctx.Event()
        self._stop_event = ctx.Event()
        self._response_qs: list = []
        self._proc = None

    def register_client(self, response_q) -> int:
        """Register a client's response queue; return its client_id.
        Must be called BEFORE ``start()`` so the queue traverses spawn."""
        if self._proc is not None:
            raise RuntimeError('InferenceServer.register_client: must register before start()')
        client_id = len(self._response_qs)
        self._response_qs.append(response_q)
        return client_id

    def start(self, wait_ready_s: float = 15.0) -> None:
        """Spawn the dedicated server process. Idempotent — calling
        twice raises."""
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
            ),
            daemon=False,
            name='InferenceServer',
        )
        self._proc.start()
        if not self._ready_event.wait(timeout=wait_ready_s):
            self.stop()
            raise TimeoutError(f'InferenceServer ready signal missed within {wait_ready_s}s')

    def forward_one(self, obs: Any, mask: Any) -> Any:
        """Synchronous in-process forward. Loopback path for tests."""
        with torch.inference_mode():
            return self.network(obs, mask) if mask is not None else self.network(obs)

    def update_network(self, state_dict: dict) -> None:
        """Update weights. In-proc mode: load directly. Spawned mode:
        push via request queue."""
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
        try:
            self.request_queue.close()
            self.request_queue.join_thread()
        except Exception:
            pass

    def device_str(self) -> str:
        return str(self.device)

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.is_alive()
