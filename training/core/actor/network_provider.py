"""Local + Remote NetworkProvider implementations.

Spec: design/network-provider.md §1.

LocalNetworkProvider holds an in-process network copy + polls weights
SHM for updates. RemoteNetworkProvider talks to an inference server
via an IPC client (Unix socket / SHM queue).
"""

from __future__ import annotations

import warnings
from typing import Any, Optional

import torch

_VALID_ACCEL = ('none', 'trace', 'compile')


class LocalNetworkProvider:
    """In-process network. ``forward`` runs in inference_mode; weights
    sync via ``update_weights`` (load_state_dict).

    ``inference_acceleration`` selects the forward path:

    - ``'none'`` (default): bypass — run the underlying network as-is.
    - ``'trace'``: lazy first-forward ``torch.jit.trace`` of the
      underlying network. Best-effort: on trace failure, log a single-
      line warning and permanently fall back to the untraced forward
      for the remainder of this provider's lifetime (no per-call retry).
      ``update_weights`` invalidates the traced module so the next
      forward re-traces with the fresh weights.
    - ``'compile'``: ``torch.compile(net, mode='reduce-overhead',
      dynamic=True)`` ONCE at ctor (NOT lazy — first forward incurs the
      compile penalty deterministically). ``dynamic=True`` is required
      for DMC-style variable-shape inputs; without it cache thrash
      makes compile slower than no compile. On compile failure, log a
      single line + fall back to raw forward for the remainder of the
      lifetime. ``update_weights`` does NOT invalidate the compiled
      module: ``torch.compile`` wraps the network whose parameter
      tensors get mutated in place by ``load_state_dict``; the compiled
      graph continues to reference the same tensors.

    ``use_jit_trace`` (bool) is a deprecated alias preserved for back-
    compat: when passed as ``True`` it is converted to
    ``inference_acceleration='trace'`` with a DeprecationWarning.

    Factory note:
        :func:`training.core.actor.provider_factory.build_network_provider`
        does NOT plumb ``inference_acceleration`` from ``InferenceCfg``
        (R7 4-field contract). Paradigms wanting to activate trace /
        compile must construct :class:`LocalNetworkProvider` directly
        — typically in the paradigm's ``mp_provider_path`` factory —
        passing ``inference_acceleration='trace' | 'compile'``
        explicitly. The generic factory path always builds with
        ``inference_acceleration='none'``.
    """

    def __init__(
        self,
        network: torch.nn.Module,
        device: str = 'cpu',
        version_tag: str = 'latest',
        inference_acceleration: str = 'none',
        use_jit_trace: bool = False,
    ) -> None:
        # Back-compat: legacy bool flag → enum value.
        if use_jit_trace:
            if inference_acceleration != 'none':
                raise ValueError(
                    'LocalNetworkProvider: cannot pass both use_jit_trace=True and '
                    f'inference_acceleration={inference_acceleration!r}; '
                    "use inference_acceleration='trace' only."
                )
            warnings.warn(
                "LocalNetworkProvider: use_jit_trace=True is deprecated, use inference_acceleration='trace' instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            inference_acceleration = 'trace'
        if inference_acceleration not in _VALID_ACCEL:
            raise ValueError(
                f'LocalNetworkProvider: inference_acceleration must be one of '
                f'{list(_VALID_ACCEL)}, got {inference_acceleration!r}'
            )

        self.network = network.to(device)
        self.network.eval()
        self._device = torch.device(device)
        self.version_tag = version_tag
        self.version = 0
        self._shm = None  # P3-B: WeightsSHM handle
        self._mode = inference_acceleration

        # Lazy state for trace path (None until first forward triggers).
        self._traced_net: Optional[torch.nn.Module] = None
        self._trace_attempted = False

        # Compile path: build ONCE at ctor (NOT lazy) so the compile
        # penalty is deterministic up front. On failure, fall back to
        # raw forward for the rest of this provider's lifetime.
        self._compiled_net: Optional[torch.nn.Module] = None
        if self._mode == 'compile':
            try:
                self._compiled_net = torch.compile(
                    self.network,
                    mode='reduce-overhead',
                    dynamic=True,
                )
            except Exception as exc:
                print(
                    f'[LocalNetworkProvider] torch.compile failed '
                    f'({type(exc).__name__}: {exc}); falling back to raw forward.'
                )
                self._compiled_net = None

    # Back-compat read accessor; tests + other call sites used this name.
    @property
    def _use_jit_trace(self) -> bool:
        return self._mode == 'trace'

    def forward(self, obs: Any, mask: Any) -> Any:
        net = self._select_net(obs, mask)
        with torch.inference_mode():
            return net(obs, mask) if mask is not None else net(obs)

    def _select_net(self, obs: Any, mask: Any) -> torch.nn.Module:
        if self._mode == 'compile':
            return self._compiled_net if self._compiled_net is not None else self.network
        if self._mode == 'trace':
            return self._maybe_trace(obs, mask)
        return self.network

    def _maybe_trace(self, obs: Any, mask: Any) -> torch.nn.Module:
        """Lazy first-forward trace. On trace failure, log + permanently
        fall back to untraced network (no per-call retry)."""
        if self._trace_attempted:
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

        - ``trace`` mode: invalidates the traced module (if any) so the
          next forward re-traces with the updated weights.
        - ``compile`` mode: does NOT invalidate the compiled module —
          ``torch.compile`` wraps ``self.network`` whose parameter
          tensors are mutated in place by ``load_state_dict``; the
          compiled graph continues to reference the same tensors.
        """
        if state_dict is not None:
            self.network.load_state_dict(state_dict)
            self.version += 1
            if self._mode == 'trace':
                self._traced_net = None
                self._trace_attempted = False
            # compile mode: parameter tensors mutated in place; compiled
            # graph continues to reference same tensors via the wrapped
            # network.
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
