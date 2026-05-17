"""Provider factory — dispatch InferenceCfg → Local | Remote.

Spec: design/network-provider.md §2.
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
        inf_cfg: validated InferenceCfg (placement + remote闭合).
        network_blueprint: pytorch network (deep-copied for local; ignored for remote).
        inference_client: required when placement='remote'.
        weights_shm: WeightsSHM handle (optional in P3-A scaffold).
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
