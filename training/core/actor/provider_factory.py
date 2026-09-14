"""Provider factory — dispatch InferenceCfg → Local | Remote.

Spec: ``openspec/specs/training-architecture/protocols.md``.
"""

from __future__ import annotations

from typing import Any, Optional

import torch.nn as nn

from training.core.actor.network_provider import (
    LocalNetworkProvider,
    RemoteNetworkProvider,
)
from training.core.config.base import InferenceCfg


def build_network_provider(
    inf_cfg: InferenceCfg,
    network_blueprint: Optional[nn.Module] = None,
    inference_client: Any = None,
    weights_shm: Any = None,
):
    """Return a NetworkProvider for the given InferenceCfg.

    Args:
        inf_cfg: validated InferenceCfg with a consistent remote section.
        network_blueprint: pytorch network (deep-copied for local; ignored for remote).
        inference_client: required when placement='remote'.
        weights_shm: optional WeightsSHM handle for local updates.

    Limitations:
        ``use_jit_trace`` is NOT plumbed from ``inf_cfg`` to
        :class:`LocalNetworkProvider` because ``InferenceCfg`` is closed
        at 4 fields (R7 contract in :mod:`training.core.config.base`).
        The flag is currently paradigm-specific (only
        ``DMCParadigmConfig`` declares it). Paradigms wanting to
        activate trace at the actor-process boot site must construct
        :class:`LocalNetworkProvider` directly in their
        ``mp_provider_path`` factory, bypassing this builder. See
        :class:`LocalNetworkProvider` for the ``use_jit_trace=True``
        ctor path.
    """
    if inf_cfg is None:
        raise ValueError('build_network_provider: inf_cfg is None')
    device = inf_cfg.device or 'cpu'

    if inf_cfg.placement == 'local':
        if network_blueprint is None:
            raise ValueError("build_network_provider: placement='local' requires network_blueprint")
        import copy

        net_copy = copy.deepcopy(network_blueprint)
        provider = LocalNetworkProvider(net_copy, device=device, version_tag=inf_cfg.version_tag)
        provider._shm = weights_shm
        return provider

    if inf_cfg.placement == 'remote':
        if inference_client is None:
            raise ValueError("build_network_provider: placement='remote' requires inference_client")
        return RemoteNetworkProvider(inference_client, version_tag=inf_cfg.version_tag)

    raise ValueError(f'build_network_provider: unknown placement {inf_cfg.placement!r}')
