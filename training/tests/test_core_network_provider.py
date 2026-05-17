"""LocalNetworkProvider + RemoteNetworkProvider + factory tests."""

from __future__ import annotations

import pytest
import torch
import torch.nn as nn

from training.core.actor.inference_client import InferenceClient
from training.core.actor.inference_server import InferenceServer
from training.core.actor.network_provider import (
    LocalNetworkProvider,
    RemoteNetworkProvider,
)
from training.core.actor.provider_factory import build_network_provider
from training.core.config.base import InferenceCfg, RemoteInferenceCfg


class _TinyNet(nn.Module):
    def __init__(self, n_in: int = 4, n_out: int = 3) -> None:
        super().__init__()
        self.fc = nn.Linear(n_in, n_out)

    def forward(self, x, mask=None):
        return self.fc(x)


def test_local_provider_forward():
    net = _TinyNet()
    prov = LocalNetworkProvider(net, device='cpu')
    x = torch.randn(1, 4)
    out = prov.forward(x, None)
    assert out.shape == (1, 3)


def test_local_provider_update_weights():
    net = _TinyNet()
    prov = LocalNetworkProvider(net, device='cpu')
    new_net = _TinyNet()
    sd = new_net.state_dict()
    v = prov.update_weights(state_dict=sd)
    assert v == 1
    v2 = prov.update_weights(state_dict=sd)
    assert v2 == 2


def test_local_provider_version_starts_zero():
    net = _TinyNet()
    prov = LocalNetworkProvider(net, device='cpu')
    assert prov.current_version() == 0


def test_remote_provider_forward_via_loopback():
    net = _TinyNet()
    server = InferenceServer(net, device='cpu')
    client = InferenceClient(server=server)
    prov = RemoteNetworkProvider(client)
    x = torch.randn(2, 4)
    out = prov.forward(x, None)
    assert out.shape == (2, 3)


def test_remote_provider_update_weights_via_state_dict_raises():
    server = InferenceServer(_TinyNet(), device='cpu')
    client = InferenceClient(server=server)
    prov = RemoteNetworkProvider(client)
    with pytest.raises(NotImplementedError):
        prov.update_weights(state_dict={})


def test_factory_local():
    net = _TinyNet()
    inf_cfg = InferenceCfg(placement='local', device='cpu')
    prov = build_network_provider(inf_cfg, network_blueprint=net)
    assert isinstance(prov, LocalNetworkProvider)
    # network is a deep copy — modify original shouldn't affect provider
    assert prov.network is not net


def test_factory_remote_requires_client():
    inf_cfg = InferenceCfg(
        placement='remote',
        device='cpu',
        remote=RemoteInferenceCfg(pool_size=1, max_batch=1, batch_timeout_ms=1),
    )
    with pytest.raises(ValueError, match='inference_client'):
        build_network_provider(inf_cfg, network_blueprint=_TinyNet())


def test_factory_unknown_placement():
    # Bypass dataclass validation by constructing manually
    inf_cfg = InferenceCfg(placement='hybrid')  # type: ignore
    with pytest.raises(ValueError, match='unknown placement'):
        build_network_provider(inf_cfg, network_blueprint=_TinyNet())


def test_factory_local_missing_network_raises():
    inf_cfg = InferenceCfg(placement='local', device='cpu')
    with pytest.raises(ValueError, match='network_blueprint'):
        build_network_provider(inf_cfg, network_blueprint=None)
