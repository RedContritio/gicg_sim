"""End-to-end smoke for the InferenceServer batched-forward path.

When the wrapped network exposes ``batched_forward``, ``_server_loop``
must (a) collect concurrent requests, (b) issue a single ActorCritic
forward via that hook, and (c) scatter the (N, max_actions) output back
to each client's response queue — all behaviourally invisible to clients
(they just call ``request`` and get a tensor back).

The test asserts that 3 clients firing near-simultaneous requests each
receive a tensor numerically equal to the in-proc per-request forward
(within float tolerance). Internal batching cannot be observed from the
client side — that's the point of the server-internal optimization. We
verify correctness via per-client numerical match.

Backwards-compat: a sibling test exercises a network WITHOUT
``batched_forward`` (a plain ``nn.Linear``) to confirm the per-request
fallback still works. ``test_inference_server_batched_multi_client`` in
``test_core_actor_mp.py`` already covers the fallback case at the mp
level; here we just sanity-check the gating predicate.
"""

from __future__ import annotations

import os
import threading

import torch

from gicg_env import GicgEnv
from training.core.actor.inference_client import InferenceClient
from training.core.actor.inference_server import InferenceServer
from training.core.network import AgentConfig
from training.paradigms.dmc._agent import DmcAgent
from training.paradigms.dmc.inference_net import DMCInferenceNet

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')


def _tiny_agent_cfg() -> AgentConfig:
    return AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_tokens_per_hook=120,
        max_actions=256,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )


def _build_env(seed: int) -> GicgEnv:
    env = GicgEnv(['赤蝶'], ['赤蝶'], seed=seed, data_dir=DATA_DIR)
    env.reset(seed=seed)
    while env._engine.phase == 1:
        env.step(0)
        if env.done:
            break
    return env


def test_inference_server_dmc_batched_path_three_clients():
    """3 clients fire requests near-simultaneously → server batches via
    DMCInferenceNet.batched_forward → each client gets a tensor matching
    the in-proc forward for its own obs."""
    torch.manual_seed(0)
    cfg = _tiny_agent_cfg()
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent.net.eval()
    inf_net = DMCInferenceNet(agent.net).eval()

    # Build 3 obs_dicts, one per client. Same env shape (赤蝶 vs 赤蝶)
    # → same n_active, so we exercise the equal-size batched path.
    obs_list: list[dict] = []
    for seed in (0, 1, 2):
        env = _build_env(seed=seed)
        agent.game_start(env.static_obs)
        obs_list.append(agent.build_obs_dict(env))
        env.close()

    # Reference outputs via in-proc forward (no server).
    with torch.inference_mode():
        ref_outs = [inf_net.forward(o) for o in obs_list]

    # batch_timeout_ms=50 + max_batch=4 ensures the server waits long
    # enough for the 3 thread-fired requests to coalesce into one batch.
    # If timing flakes (only 2 of 3 land in the first batch), the 3rd
    # falls through to the next batch's path — still correct, still
    # numerically equal. Test verifies correctness, not batch composition.
    server = InferenceServer(inf_net, device='cpu', max_batch=4, batch_timeout_ms=50)
    clients = [InferenceClient.attach_to_server(server, timeout_ms=15000) for _ in range(3)]
    server.start(wait_ready_s=15.0)

    results: list = [None, None, None]
    errors: list = [None, None, None]

    def _fire(idx: int) -> None:
        try:
            results[idx] = clients[idx].request(obs_list[idx], None)
        except Exception as exc:
            errors[idx] = exc

    try:
        threads = [threading.Thread(target=_fire, args=(i,)) for i in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20.0)
        for i, err in enumerate(errors):
            assert err is None, f'client {i} raised: {err!r}'
        for i, res in enumerate(results):
            assert res is not None, f'client {i} got no response'
            assert isinstance(res, torch.Tensor)
            assert res.shape == ref_outs[i].shape, f'client {i} shape mismatch: {res.shape} vs ref {ref_outs[i].shape}'
            assert torch.allclose(res, ref_outs[i], atol=1e-5), (
                f'client {i} numerically diverged from in-proc forward, max diff {(res - ref_outs[i]).abs().max()}'
            )
    finally:
        for c in clients:
            c.close()
        server.stop()


class _TinyNoBatchedNet(torch.nn.Module):
    """Plain nn.Module with no ``batched_forward``; exercises the
    per-request fallback path even when batch coalesces N>1 requests."""

    def __init__(self) -> None:
        super().__init__()
        self.fc = torch.nn.Linear(4, 3)

    def forward(self, x, mask=None):
        return self.fc(x)


def test_inference_server_fallback_when_no_batched_forward():
    """Network without ``batched_forward`` → per-request loop runs even
    when multiple requests coalesce in one server tick. Verifies the
    gating predicate (``hasattr(network, 'batched_forward') and
    len(batch) > 1``) does not break legacy callers (AZ + plain test
    nets)."""
    net = _TinyNoBatchedNet()
    assert not hasattr(net, 'batched_forward')  # premise of this test

    server = InferenceServer(net, device='cpu', max_batch=4, batch_timeout_ms=50)
    c1 = InferenceClient.attach_to_server(server, timeout_ms=10000)
    c2 = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)

    results: list = [None, None]
    errors: list = [None, None]

    def _fire(idx: int, client, x) -> None:
        try:
            results[idx] = client.request(x, None)
        except Exception as exc:
            errors[idx] = exc

    try:
        x1 = torch.randn(1, 4)
        x2 = torch.randn(1, 4)
        threads = [
            threading.Thread(target=_fire, args=(0, c1, x1)),
            threading.Thread(target=_fire, args=(1, c2, x2)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15.0)
        for i, err in enumerate(errors):
            assert err is None, f'client {i} raised: {err!r}'
        with torch.inference_mode():
            ref1 = net(x1)
            ref2 = net(x2)
        assert torch.allclose(results[0], ref1, atol=1e-6)
        assert torch.allclose(results[1], ref2, atol=1e-6)
    finally:
        c1.close()
        c2.close()
        server.stop()


def test_inference_server_dmc_single_request_uses_fallback():
    """Single request → ``len(batch) > 1`` is False → falls through to
    per-request path. Correctness must hold; this guards against an
    off-by-one in the gating predicate (e.g. ``>=`` vs ``>``)."""
    torch.manual_seed(0)
    cfg = _tiny_agent_cfg()
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent.net.eval()
    inf_net = DMCInferenceNet(agent.net).eval()
    env = _build_env(seed=0)
    agent.game_start(env.static_obs)
    obs = agent.build_obs_dict(env)
    env.close()
    with torch.inference_mode():
        ref = inf_net.forward(obs)

    server = InferenceServer(inf_net, device='cpu', max_batch=4, batch_timeout_ms=5)
    client = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)
    try:
        out = client.request(obs, None)
        assert out.shape == ref.shape
        assert torch.allclose(out, ref, atol=1e-5)
    finally:
        client.close()
        server.stop()
