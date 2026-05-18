"""Local + Remote NetworkProvider implementations.

Spec: design/network-provider.md §1.

LocalNetworkProvider holds an in-process network copy + polls weights
SHM for updates. RemoteNetworkProvider talks to an inference server
via an IPC client (Unix socket / SHM queue).
"""

from __future__ import annotations

from typing import Any, Optional

import torch


class LocalNetworkProvider:
    """In-process network. ``forward`` runs in inference_mode; weights
    sync via ``update_weights`` (load_state_dict).

    ``use_jit_trace=True`` enables lazy first-forward ``torch.jit.trace``
    of the underlying network. Best-effort: on trace failure, log a
    single-line warning and permanently fall back to the untraced
    forward for the remainder of this provider's lifetime (no per-call
    retry). ``update_weights`` invalidates the traced module so the next
    forward re-traces with the fresh weights.

    Factory note:
        :func:`training.core.actor.provider_factory.build_network_provider`
        does NOT plumb ``use_jit_trace`` from ``InferenceCfg`` (R7
        4-field contract). Paradigms wanting to activate trace must
        construct :class:`LocalNetworkProvider` directly — typically in
        the paradigm's ``mp_provider_path`` factory — passing
        ``use_jit_trace=True`` explicitly. The generic factory path
        always builds with ``use_jit_trace=False``.
    """

    def __init__(
        self,
        network: torch.nn.Module,
        device: str = 'cpu',
        version_tag: str = 'latest',
        use_jit_trace: bool = False,
    ) -> None:
        self.network = network.to(device)
        self.network.eval()
        self._device = torch.device(device)
        self.version_tag = version_tag
        self.version = 0
        self._shm = None  # P3-B: WeightsSHM handle
        self._use_jit_trace = use_jit_trace
        self._traced_net: Optional[torch.nn.Module] = None  # lazy: first forward attempts trace
        self._trace_attempted = False  # one-shot guard, no retry after failure

    def forward(self, obs: Any, mask: Any) -> Any:
        net = self._maybe_trace(obs, mask)
        with torch.inference_mode():
            return net(obs, mask) if mask is not None else net(obs)

    def _maybe_trace(self, obs: Any, mask: Any) -> torch.nn.Module:
        """Lazy first-forward trace. On trace failure, log + permanently
        fall back to untraced network (no per-call retry)."""
        if not self._use_jit_trace or self._trace_attempted:
            return self._traced_net if self._traced_net is not None else self.network
        self._trace_attempted = True
        try:
            example = (obs, mask) if mask is not None else (obs,)
            self._traced_net = torch.jit.trace(self.network, example, check_trace=False)
        except Exception as exc:
            print(
                f'[LocalNetworkProvider] torch.jit.trace failed ({type(exc).__name__}: {exc}); '
                f'falling back to untraced forward for remainder of process lifetime.'
            )
            self._traced_net = None
        return self._traced_net if self._traced_net is not None else self.network

    def update_weights(self, version_tag: Optional[str] = None, state_dict: Optional[dict] = None) -> int:
        """Two modes:
        - Direct: pass ``state_dict`` to load right now (used by tests
          + serial mode).
        - SHM: pass ``version_tag``; provider pulls from WeightsSHM if
          attached (P3-B wiring).

        Invalidates the traced module (if any) so the next forward
        re-traces with the updated weights.
        """
        if state_dict is not None:
            self.network.load_state_dict(state_dict)
            self.version += 1
            # Invalidate traced module so next forward re-traces with new weights.
            if self._use_jit_trace:
                self._traced_net = None
                self._trace_attempted = False
            return self.version
        # SHM-driven path (no-op in P3-A scaffold; full impl P3-B).
        if self._shm is not None:
            # TODO(P3-B): self._shm.read(version_tag or self.version_tag)
            pass
        return self.version

    def current_version(self) -> int:
        return self.version

    def device(self) -> torch.device:
        return self._device

    def close(self) -> None:
        self._shm = None


class RemoteNetworkProvider:
    """Remote inference. ``forward`` serializes obs → IPC client →
    server batched forward → response. ``update_weights`` is no-op
    (server owns weights via its own watcher)."""

    def __init__(self, client: Any, version_tag: str = 'latest') -> None:
        self.client = client
        self.version_tag = version_tag
        self.version = 0

    def forward(self, obs: Any, mask: Any) -> Any:
        return self.client.request(obs, mask, self.version_tag)

    def update_weights(self, version_tag: Optional[str] = None, state_dict: Optional[dict] = None) -> int:
        # Server owns weights; client only updates its view of the latest
        # known version (reported via response headers in P3-B impl).
        if state_dict is not None:
            raise NotImplementedError('RemoteNetworkProvider.update_weights: weights managed by server')
        # P3-B: query server for latest version
        return self.version

    def current_version(self) -> int:
        return self.version

    def device(self) -> torch.device:
        # Remote — device is server-side; client returns its known view.
        if hasattr(self.client, 'server_device'):
            return torch.device(self.client.server_device())
        return torch.device('cpu')

    def close(self) -> None:
        if hasattr(self.client, 'close'):
            self.client.close()
