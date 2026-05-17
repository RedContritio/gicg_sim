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
    sync via ``update_weights`` (load_state_dict)."""

    def __init__(self, network: torch.nn.Module, device: str = 'cpu', version_tag: str = 'latest') -> None:
        self.network = network.to(device)
        self.network.eval()
        self._device = torch.device(device)
        self.version_tag = version_tag
        self.version = 0
        self._shm = None  # P3-B: WeightsSHM handle

    def forward(self, obs: Any, mask: Any) -> Any:
        with torch.inference_mode():
            return self.network(obs, mask) if mask is not None else self.network(obs)

    def update_weights(self, version_tag: Optional[str] = None, state_dict: Optional[dict] = None) -> int:
        """Two modes:
        - Direct: pass ``state_dict`` to load right now (used by tests
          + serial mode).
        - SHM: pass ``version_tag``; provider pulls from WeightsSHM if
          attached (P3-B wiring).
        """
        if state_dict is not None:
            self.network.load_state_dict(state_dict)
            self.version += 1
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
