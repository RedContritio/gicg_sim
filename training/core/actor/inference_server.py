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

The child-process loop body lives in
:mod:`training.core.actor.inference_server_loop`; this module owns the
main-process handle whose import path is public.
"""

from __future__ import annotations

import pickle
import warnings
from typing import Any, Optional

import torch

from training.core.actor._mp_helpers import get_ctx
from training.core.actor.inference_server_loop import _server_loop

_VALID_ACCEL = ('none', 'trace', 'compile')


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
