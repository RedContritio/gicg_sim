"""InferenceClient — RPC stub talking to InferenceServer.

Three modes:

1. **Loopback (in-proc)** — pass ``server=`` an :class:`InferenceServer`.
   ``request`` calls ``server.forward_one`` directly. Used by tests +
   serial-mode wiring (P3-A backwards compat).
2. **Spawned (real RPC)** — call :meth:`attach_to_server` (parent side,
   before server.start()) to register a response queue + receive a
   ``client_id``. The client then sends ``('infer', client_id, req_id,
   obs_bytes, mask_bytes)`` over the server's request queue and blocks
   on its own response queue until the matching reply arrives.
3. Unattached — both ``server`` and ``request_queue`` None — any
   ``request`` raises.

Loopback mode is unchanged from P3-A. Spawned mode is the new path used
by ``Runtime`` when ``inf_cfg.placement == 'remote'``.
"""

from __future__ import annotations

import pickle
import uuid
from typing import Any

from training.core.actor._mp_helpers import get_ctx


def _to_bytes(t: Any) -> bytes:
    return pickle.dumps(t, protocol=pickle.HIGHEST_PROTOCOL)


def _from_bytes(b: bytes) -> Any:
    return pickle.loads(b)


class InferenceClient:
    """RPC client for InferenceServer. See module doc for the 3 modes."""

    def __init__(
        self,
        server: Any = None,
        request_queue: Any = None,
        response_queue: Any = None,
        client_id: int = -1,
        socket_path: str = '',
        timeout_ms: int = 30000,
        server_device: str = 'cpu',
    ) -> None:
        self.server = server
        self.request_queue = request_queue
        self.response_queue = response_queue
        self.client_id = client_id
        self.socket_path = socket_path
        self.timeout_ms = timeout_ms
        self._server_device = server_device

    @classmethod
    def attach_to_server(
        cls,
        server: 'Any',
        timeout_ms: int = 30000,
    ) -> 'InferenceClient':
        """Convenience constructor — registers a fresh response queue
        with the (not-yet-started) server + returns a wired client."""
        ctx = get_ctx()
        resp_q = ctx.Queue()
        client_id = server.register_client(resp_q)
        return cls(
            request_queue=server.request_queue,
            response_queue=resp_q,
            client_id=client_id,
            timeout_ms=timeout_ms,
            server_device=server.device_str(),
        )

    def request(self, obs: Any, mask: Any, version_tag: str = 'latest') -> Any:
        # Loopback: direct call.
        if self.server is not None:
            return self.server.forward_one(obs, mask)
        if self.request_queue is None or self.response_queue is None or self.client_id < 0:
            raise RuntimeError(
                'InferenceClient.request: no transport — pass server= (loopback) or use attach_to_server (RPC)',
            )
        req_id = uuid.uuid4().hex
        mask_bytes = _to_bytes(mask) if mask is not None else None
        self.request_queue.put(
            ('infer', self.client_id, req_id, _to_bytes(obs), mask_bytes),
        )
        timeout_s = self.timeout_ms / 1000.0
        status, resp_id, payload = self.response_queue.get(timeout=timeout_s)
        if resp_id != req_id:
            raise RuntimeError(f'InferenceClient.request: reply id mismatch {resp_id} != {req_id}')
        if status == 'err':
            raise RuntimeError(f'InferenceServer forward failed: {payload}')
        return _from_bytes(payload)

    def server_device(self) -> str:
        if self.server is not None:
            return self.server.device_str()
        return self._server_device

    def close(self) -> None:
        self.server = None
        if self.response_queue is not None:
            # cancel_join_thread before close avoids the actor-side
            # atexit deadlock when our peer (the spawned InferenceServer
            # process) has died with our pending reply in flight. We
            # don't care about pending replies at shutdown.
            try:
                self.response_queue.cancel_join_thread()
            except Exception:
                pass
            try:
                self.response_queue.close()
            except Exception:
                pass
            self.response_queue = None
