"""End-to-end DMC mp mode wiring smoke (E target / P2-PoC).

Verifies the parent → actor InferenceClient threading + shared
InferenceServer path:

- ``DMCMultiProcessCollector._bootstrap`` constructs the
  :class:`InferenceServer` and N :class:`InferenceClient` instances.
- Each actor receives its client through the ``inference_client``
  kwarg (added to ``actor_main`` in this commit).
- ``build_dmc_provider`` returns a remote provider routed via the
  client; actor forwards go to the shared server.

device='cpu' verifies the architecture compiles + actors spawn on Mac
without GPU dependency. GPU benchmark is deferred to the Windows-side
follow-up (see ``training/paradigms/dmc/PLAN.md`` E target).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from training.core.config.loader import load_cfg


def test_dmc_mp_factories_end_to_end():
    cfg = load_cfg(Path('configs/dmc/gpu_async.toml'), overrides=[])
    assert cfg.meta.paradigm == 'dmc'
    assert cfg.pipeline.mode == 'async'

    from training.core.env_factory import make_env_factory
    from training.paradigms import resolve as resolve_paradigm

    paradigm = resolve_paradigm('dmc')
    network = paradigm.make_network(cfg)
    opp_pool = paradigm.make_opponent_pool(cfg, network)
    env_factory = make_env_factory(cfg, None, master_seed=cfg.meta.seed)
    collector = paradigm.make_collector(cfg, env_factory, network, opp_pool)

    try:
        # First collect triggers _bootstrap (spawns InferenceServer +
        # clients + actors). Subsequent polls drain the ring as actors
        # push transitions.
        out = collector.collect(n_episodes=4, provider=None)
        n_trans = out.n_units
        deadline = time.time() + 20
        while n_trans == 0 and time.time() < deadline:
            time.sleep(0.5)
            out = collector.collect(n_episodes=4, provider=None)
            n_trans = out.n_units
        # Architectural wiring assertion — at least one transition must
        # round-trip through actor → server → response. If this fails,
        # the InferenceClient threading or obs_dict adapter is broken.
        assert n_trans > 0, 'no transitions collected within 20s — mp wiring broken'
    finally:
        collector.close()


def test_build_dmc_provider_requires_inference_client():
    """``build_dmc_provider`` raises if ``inference_client`` kwarg is
    missing — CS4 strict (no LocalNetworkProvider fallback in mp mode).
    """
    from training.paradigms.dmc.mp_factories import build_dmc_provider

    class _Cfg:
        pass

    with pytest.raises(ValueError, match='inference_client kwarg required'):
        build_dmc_provider(_Cfg(), actor_id=0)


def test_decode_dmc_request_matches_legacy_torch_path():
    """Numerical equivalence: server-side decoder output for a numpy
    payload must match the legacy DmcAgent.build_obs_dict path
    (everything that flows into ``DMCInferenceNet.forward``).

    Guards the decode-offload (2026-05-20): if the server-side static
    re-encode diverges from ``DmcAgent.encode_static`` for the same
    network weights, downstream Q values drift and training silently
    regresses. Test runs everything in-proc (no IPC) so a failure
    points directly at decoder logic, not transport.
    """
    import pickle

    import numpy as np
    import torch

    from training.core.network import AgentConfig
    from training.paradigms.dmc._agent import DmcAgent
    from training.paradigms.dmc.inference_net import DMCInferenceNet
    from training.paradigms.dmc.mp_factories import decode_dmc_request
    from training.core.step_encoding import pad_action_payments, pad_action_refs

    import os

    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    from gicg_env import GicgEnv

    torch.manual_seed(0)
    cfg = AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_ops_per_hook=64,
        max_actions=256,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)
    agent.net.eval()
    inf_net = DMCInferenceNet(agent.net).eval()

    env = GicgEnv(['赤蝶'], ['赤蝶'], seed=0, data_dir=data_dir)
    env.reset(seed=0)
    while env.phase == 1:
        env.step(0)
        if env.done:
            break

    # Legacy torch path
    agent.game_start(env.static_obs)
    ref_obs_dict = agent.build_obs_dict(env)
    with torch.inference_mode():
        ref_out = inf_net.forward(ref_obs_dict)

    # New numpy-payload path with hash-keyed shared cache
    import hashlib

    static_obs_np = np.ascontiguousarray(env.static_obs, dtype=np.float32)
    static_obs_hash = hashlib.sha256(static_obs_np.tobytes()).digest()[:16]
    dyn_obs_np = np.ascontiguousarray(env._get_obs(), dtype=np.float32)
    refs_np = env.get_action_refs()
    pay_np = env.get_legal_action_payments()
    refs_padded = pad_action_refs(refs_np, cfg.max_actions)
    pay_padded = pad_action_payments(pay_np, cfg.max_actions)
    payload = {
        'static_obs_hash': static_obs_hash,
        'static_obs': static_obs_np,
        'dyn_obs': dyn_obs_np,
        'refs_padded': refs_padded.astype(np.int64),
        'pay_padded': pay_padded.astype(np.float32),
    }
    payload_bytes = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
    shared_cache: dict = {}
    obs_dict, _mask = decode_dmc_request(payload_bytes, None, 'cpu', shared_cache, inf_net)
    with torch.inference_mode():
        new_out = inf_net.forward(obs_dict)

    assert new_out.shape == ref_out.shape, f'shape mismatch: {new_out.shape} vs {ref_out.shape}'
    diff = (new_out - ref_out).abs().max().item()
    assert diff < 1e-5, f'numerical divergence: max abs diff = {diff}'
    # Hash now populated in shared_cache.
    assert static_obs_hash in shared_cache, 'expected static_obs_hash to be cached'

    # Second request on same env: no static_obs embedded, cache hit by hash.
    payload2 = {
        'static_obs_hash': static_obs_hash,
        'static_obs': None,
        'dyn_obs': dyn_obs_np,
        'refs_padded': refs_padded.astype(np.int64),
        'pay_padded': pay_padded.astype(np.float32),
    }
    payload2_bytes = pickle.dumps(payload2, protocol=pickle.HIGHEST_PROTOCOL)
    obs_dict2, _ = decode_dmc_request(payload2_bytes, None, 'cpu', shared_cache, inf_net)
    with torch.inference_mode():
        new_out2 = inf_net.forward(obs_dict2)
    # Same dynamic input → same output (cached static).
    assert (new_out2 - new_out).abs().max().item() < 1e-6

    # Cache miss without static_obs → raises loudly.
    empty_cache: dict = {}
    with pytest.raises(RuntimeError, match='cache miss for hash='):
        decode_dmc_request(payload2_bytes, None, 'cpu', empty_cache, inf_net)

    env.close()


def test_capture_obs_np_matches_legacy_capture_obs():
    """Buffer-side numpy capture must produce per-key arrays that match
    the legacy ``capture_obs(env, agent)`` output (modulo dtype). DMC
    collector pulls ``last_obs_dict`` off the actor side into
    ``DmcTransition``; a shape/dtype regression breaks ``collate_batch``
    silently.
    """
    import os

    import numpy as np
    import torch

    from training.core.network import AgentConfig
    from training.paradigms.dmc._agent import DmcAgent
    from training.paradigms.dmc._episode import capture_obs
    from training.paradigms.dmc.mp_factories import _capture_obs_np, _encode_static_np
    from gicg_env import GicgEnv

    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    torch.manual_seed(0)
    cfg = AgentConfig(
        n_counter_slots=2 * 6 * 128 + 2 * 140 + 16,
        n_hooks=900,
        max_ops_per_hook=64,
        max_actions=256,
        d_model=16,
        n_cross_layers=1,
        dropout=0.0,
    )
    agent = DmcAgent(cfg, device='cpu', lr=1e-4, epsilon=0.0)

    env = GicgEnv(['赤蝶'], ['赤蝶'], seed=0, data_dir=data_dir)
    env.reset(seed=0)
    while env.phase == 1:
        env.step(0)
        if env.done:
            break

    agent.game_start(env.static_obs)
    legacy = capture_obs(env, agent)

    # Numpy path
    static_obs_np = np.ascontiguousarray(env.static_obs, dtype=np.float32)
    static_np = _encode_static_np(
        static_obs_np,
        n_counter_slots=cfg.n_counter_slots,
        n_hooks=cfg.n_hooks,
        max_ops_per_hook=cfg.max_ops_per_hook,
        fields_per_op=cfg.fields_per_op,
    )
    dyn_obs = np.ascontiguousarray(env._get_obs(), dtype=np.float32)
    kinds, _ = env.get_legal_actions()
    n_legal = int(len(kinds))
    # I29 P2 wire v3 — refs/pay 是 nlegal-sized;collate_batch pad 到 max_actions。
    refs_nlegal = np.asarray(env.get_action_refs(), dtype=np.int64)[:n_legal]
    pay_nlegal = np.asarray(env.get_legal_action_payments(), dtype=np.float32)[:n_legal]
    new = _capture_obs_np(
        dyn_obs=dyn_obs,
        n_legal=n_legal,
        refs_nlegal=refs_nlegal,
        pay_nlegal=pay_nlegal,
        n_counter_slots=cfg.n_counter_slots,
        static_np=static_np,
    )

    # All keys + shapes must match.
    assert set(new.keys()) == set(legacy.keys()), (
        f'key drift: new={sorted(new.keys())} vs legacy={sorted(legacy.keys())}'
    )
    for k, v in legacy.items():
        if k == 'n_legal':
            assert new[k] == v, f'n_legal mismatch'
            continue
        assert new[k].shape == v.shape, f'shape mismatch on {k}: {new[k].shape} vs {v.shape}'
        # Allow floating-point tolerance on float arrays
        if v.dtype.kind == 'f':
            assert np.allclose(new[k], v, atol=1e-6), f'value mismatch on {k}'
        else:
            assert np.array_equal(new[k], v), f'value mismatch on {k}'

    env.close()
