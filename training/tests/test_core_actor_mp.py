"""Real-multiprocessing tests for training/core/actor (FU-W3a).

Covers SHMRing / WeightsSHM / IPCQueue / InferenceServer (spawned +
loopback) / ActorProcess / Runtime / SharedBufferAdapter. All tests
use the spawn ctx (mac/Linux parity) + self-contained fixtures →
xdist-safe."""

from __future__ import annotations

import os
import time

import pytest
import torch
import torch.nn as nn

from training.core.actor._mp_helpers import get_ctx
from training.core.actor.actor_process import ActorProcess
from training.core.actor.inference_client import InferenceClient
from training.core.actor.inference_server import InferenceServer
from training.core.actor.ipc.queue import IPCQueue
from training.core.actor.ipc.ring import SHMRing
from training.core.actor.runtime import Runtime
from training.core.actor.weights_shm import WeightsSHM, latest_version


# ---------- SHMRing ---------- #


def _ring_pusher(ring_info: dict, n: int) -> None:
    """Top-level spawn target — re-attach + push N items."""
    ring = SHMRing.attach(ring_info)
    for i in range(n):
        ok = ring.push({'idx': i, 'pid': os.getpid()})
        assert ok, f'ring full at i={i}'
    ring.close()


def test_shm_ring_cross_process_push_pop():
    ring = SHMRing(capacity=16, slot_payload_max=4096)
    ctx = get_ctx()
    p = ctx.Process(target=_ring_pusher, args=(ring.serialize(), 8))
    p.start()
    p.join(timeout=10)
    assert not p.is_alive()
    items = []
    for _ in range(8):
        item = ring.try_pop()
        assert item is not None
        items.append(item)
    assert [x['idx'] for x in items] == list(range(8))
    # All from the spawned child.
    assert all(x['pid'] != os.getpid() for x in items)
    assert ring.try_pop() is None
    ring.close()


def test_shm_ring_full_returns_false():
    ring = SHMRing(capacity=3, slot_payload_max=1024)
    assert ring.push('a') is True
    assert ring.push('b') is True
    assert ring.push('c') is True
    assert ring.push('d') is False
    assert ring.try_pop() == 'a'
    assert ring.push('d') is True
    ring.close()


def test_shm_ring_payload_too_large_raises():
    ring = SHMRing(capacity=2, slot_payload_max=64)
    big = 'x' * 10000
    with pytest.raises(ValueError, match='slot_payload_max'):
        ring.push(big)
    ring.close()


def _ring_multi_pusher(ring_info: dict, worker_id: int, n: int) -> None:
    ring = SHMRing.attach(ring_info)
    for i in range(n):
        while True:
            if ring.push((worker_id, i)):
                break
            time.sleep(0.001)
    ring.close()


def test_shm_ring_multi_producer():
    ring = SHMRing(capacity=128, slot_payload_max=1024)
    ctx = get_ctx()
    procs = [ctx.Process(target=_ring_multi_pusher, args=(ring.serialize(), wid, 20)) for wid in range(3)]
    for p in procs:
        p.start()
    # Drain concurrently with producers.
    seen = []
    deadline = time.time() + 15
    while len(seen) < 60 and time.time() < deadline:
        item = ring.try_pop()
        if item is not None:
            seen.append(item)
        else:
            time.sleep(0.005)
    for p in procs:
        p.join(timeout=5)
    # Drain any stragglers.
    while True:
        item = ring.try_pop()
        if item is None:
            break
        seen.append(item)
    assert len(seen) == 60
    # All 3 workers contributed.
    workers_seen = {w for (w, _) in seen}
    assert workers_seen == {0, 1, 2}
    ring.close()


# ---------- WeightsSHM ---------- #


def _weights_reader(shm_info: dict, tag: str, return_q) -> None:
    """Read slot in a child and report version + n params back."""
    shm = WeightsSHM.attach(shm_info)
    sd, ver = shm.read(tag)
    n_params = sum(t.numel() for t in sd.values()) if sd is not None else 0
    return_q.put((ver, n_params))


def test_weights_shm_cross_process_read():
    shm = WeightsSHM(max_state_dict_bytes=4 * 1024 * 1024)
    net = nn.Linear(4, 3)
    sd = {k: v.cpu() for k, v in net.state_dict().items()}
    shm.write('latest', sd, version=7)

    ctx = get_ctx()
    q = ctx.Queue()
    p = ctx.Process(target=_weights_reader, args=(shm.serialize_for_worker(['latest']), 'latest', q))
    p.start()
    p.join(timeout=10)
    assert not p.is_alive()
    ver, n_params = q.get(timeout=2)
    assert ver == 7
    expected = sum(t.numel() for t in sd.values())
    assert n_params == expected
    shm.close()


def test_weights_shm_versioned_slot_snapshot():
    shm = WeightsSHM(max_state_dict_bytes=1024 * 1024)
    net_a = nn.Linear(2, 2)
    net_b = nn.Linear(2, 2)
    shm.write('latest', net_a.state_dict(), version=1)
    shm.snapshot('latest', 'snapshot_eval_0')
    # Mutate latest.
    shm.write('latest', net_b.state_dict(), version=2)
    sd_eval, v_eval = shm.read('snapshot_eval_0')
    sd_latest, v_latest = shm.read('latest')
    assert v_eval == 1
    assert v_latest == 2
    # eval snapshot is net_a, latest is net_b — weights differ.
    assert not torch.allclose(sd_eval['weight'], sd_latest['weight'])
    shm.close()


def test_weights_shm_cold_start_returns_none():
    shm = WeightsSHM(max_state_dict_bytes=64 * 1024)
    sd, v = shm.read('latest')
    assert sd is None
    assert v == -1
    assert latest_version(shm, 'latest') is None
    shm.close()


def test_weights_shm_oversize_raises():
    shm = WeightsSHM(max_state_dict_bytes=1024)
    big = {'w': torch.zeros(10000)}  # ~40KB > 1KB
    with pytest.raises(ValueError, match='max'):
        shm.write('latest', big, version=1)
    shm.close()


# ---------- IPCQueue ---------- #


def _ipc_q_producer(q: IPCQueue, n: int) -> None:
    for i in range(n):
        q.put(f'item-{i}')


def test_ipc_queue_cross_process():
    q = IPCQueue(maxsize=64)
    ctx = get_ctx()
    p = ctx.Process(target=_ipc_q_producer, args=(q, 5))
    p.start()
    p.join(timeout=5)
    received = []
    deadline = time.time() + 3
    while len(received) < 5 and time.time() < deadline:
        try:
            received.append(q.get(timeout=0.5))
        except Exception:
            break
    assert received == [f'item-{i}' for i in range(5)]
    q.close()


# ---------- InferenceServer ---------- #


class _TinyNet(nn.Module):
    def __init__(self) -> None:
        super().__init__()
        self.fc = nn.Linear(4, 3)

    def forward(self, x, mask=None):
        return self.fc(x)


def test_inference_server_spawned_round_trip():
    net = _TinyNet()
    server = InferenceServer(net, device='cpu', max_batch=4, batch_timeout_ms=5)
    client = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)
    try:
        assert server.is_running()
        x = torch.randn(2, 4)
        out = client.request(x, None)
        assert out.shape == (2, 3)
        # Compare numerically to in-proc forward (loopback).
        with torch.inference_mode():
            ref = net(x)
        assert torch.allclose(out, ref, atol=1e-6)
    finally:
        client.close()
        server.stop()
    assert not server.is_running()


def test_inference_server_batched_multi_client():
    """Two clients, each fires N requests interleaved; both see correct
    replies (no cross-talk)."""
    net = _TinyNet()
    server = InferenceServer(net, device='cpu', max_batch=4, batch_timeout_ms=5)
    c1 = InferenceClient.attach_to_server(server, timeout_ms=10000)
    c2 = InferenceClient.attach_to_server(server, timeout_ms=10000)
    server.start(wait_ready_s=15.0)
    try:
        for i in range(5):
            x1 = torch.randn(1, 4)
            x2 = torch.randn(1, 4)
            r1 = c1.request(x1, None)
            r2 = c2.request(x2, None)
            with torch.inference_mode():
                ref1 = net(x1)
                ref2 = net(x2)
            assert torch.allclose(r1, ref1, atol=1e-6)
            assert torch.allclose(r2, ref2, atol=1e-6)
    finally:
        c1.close()
        c2.close()
        server.stop()


def test_inference_server_loopback_still_works():
    """Backward compat: ``server=`` arg path (P3-A) still functions."""
    net = _TinyNet()
    server = InferenceServer(net, device='cpu')
    client = InferenceClient(server=server)
    x = torch.randn(1, 4)
    out = client.request(x, None)
    assert out.shape == (1, 3)


def test_inference_server_double_start_raises():
    server = InferenceServer(_TinyNet(), device='cpu')
    server.start(wait_ready_s=15.0)
    try:
        with pytest.raises(RuntimeError, match='already started'):
            server.start()
    finally:
        server.stop()


# ---------- ActorProcess + Runtime ---------- #


# Top-level builders for spawn safety.
def _smoke_env_factory(cfg, seed):
    def _factory(scenario_seed):
        return _SmokeEnv(scenario_seed)

    return _factory


def _smoke_opp_registry(cfg):
    from training.core.eval.baselines import OpponentRegistry

    reg = OpponentRegistry()
    reg.register('always_zero', lambda seed, params: _AlwaysZero())
    return reg


def _smoke_policy(cfg, actor_id):
    return _SmokePolicy()


def _smoke_provider(cfg, actor_id):
    return _SmokeProvider()


def _smoke_spec_sampler(cfg, actor_id):
    from training.core.protocols import EpisodeSpec

    return EpisodeSpec(scenario_seed=actor_id, opponent_id='always_zero')


class _SmokeEnv:
    def __init__(self, seed):
        self.seed = seed
        self.step_n = 0
        self.done = False
        self.current_player = 0
        self._engine = self
        self.winner = -1

    def get_obs(self):
        return f'obs{self.step_n}'

    def get_legal_actions(self):
        return [0, 1], None

    def step(self, a):
        self.step_n += 1
        if self.step_n >= 2:
            self.done = True
            self.winner = 0
        self.current_player = self.step_n % 2
        return None, 0.0, self.done, {}


class _SmokePolicy:
    def reset(self):
        pass

    def act(self, obs, mask, provider):
        return 0, {}


class _SmokeProvider:
    def forward(self, obs, mask):
        return {}

    def update_weights(self, version_tag=None):
        return 1

    def current_version(self):
        return 1

    def close(self):
        pass


class _AlwaysZero:
    def select_action(self, env):
        return 0


class _MetaCfg:
    seed = 0


class _SmokeCfg:
    meta = _MetaCfg()


def test_actor_process_spawn_and_terminate():
    cfg = _SmokeCfg()
    q = IPCQueue(maxsize=128)
    kwargs = {
        'build_env_factory_path': 'training.tests.test_core_actor_mp._smoke_env_factory',
        'build_opp_registry_path': 'training.tests.test_core_actor_mp._smoke_opp_registry',
        'build_policy_path': 'training.tests.test_core_actor_mp._smoke_policy',
        'build_provider_path': 'training.tests.test_core_actor_mp._smoke_provider',
        'spec_sampler_path': 'training.tests.test_core_actor_mp._smoke_spec_sampler',
        'transition_queue': q,
    }
    ap = ActorProcess(actor_id=0, cfg=cfg, kwargs=kwargs)
    ap.spawn()
    assert ap.pid is not None
    # Give actor time to produce transitions.
    deadline = time.time() + 10
    collected = 0
    while time.time() < deadline and collected < 3:
        try:
            item = q.get(timeout=0.5)
            collected += 1
            assert isinstance(item, list)  # list[Transition]
        except Exception:
            pass
    assert collected >= 1, 'actor produced no transitions in 10s'
    ap.terminate(timeout_s=5.0)
    assert not ap.is_alive()
    q.close()


def test_runtime_lifecycle():
    cfg = _SmokeCfg()
    q = IPCQueue(maxsize=128)
    kwargs = {
        'build_env_factory_path': 'training.tests.test_core_actor_mp._smoke_env_factory',
        'build_opp_registry_path': 'training.tests.test_core_actor_mp._smoke_opp_registry',
        'build_policy_path': 'training.tests.test_core_actor_mp._smoke_policy',
        'build_provider_path': 'training.tests.test_core_actor_mp._smoke_provider',
        'spec_sampler_path': 'training.tests.test_core_actor_mp._smoke_spec_sampler',
        'transition_queue': q,
    }
    rt = Runtime(cfg)
    try:
        actors = rt.start_actors(n_actors=2, actor_kwargs_factory=lambda i: dict(kwargs))
        assert len(actors) == 2
        # Wait for at least one transition from each actor.
        time.sleep(1.5)
        # Publish a weights blob (smoke).
        net = nn.Linear(2, 2)
        rt.publish_weights(net.state_dict(), version=1)
        ver = latest_version(rt.weights_shm, 'latest')
        assert ver == 1
        snap_ver = rt.snapshot_for_eval('eval0')
        assert snap_ver == 1
    finally:
        rt.close()
    for ap in actors:
        assert not ap.is_alive()
    q.close()


def test_actor_process_missing_kwargs_raises_in_child():
    """If we forget to pass a builder, the child should die quickly
    rather than spin silently."""
    cfg = _SmokeCfg()
    kwargs = {
        # Only one builder + transition_queue — missing others.
        'build_env_factory_path': 'training.tests.test_core_actor_mp._smoke_env_factory',
        'transition_queue': IPCQueue(maxsize=4),
    }
    ap = ActorProcess(actor_id=99, cfg=cfg, kwargs=kwargs)
    ap.spawn()
    # Child should exit on the ValueError raise inside actor_main.
    deadline = time.time() + 5
    while time.time() < deadline and ap.is_alive():
        time.sleep(0.1)
    assert not ap.is_alive(), 'child should have exited on missing-kwargs ValueError'
    ap.terminate()


# ---------- SharedBufferAdapter ---------- #


def test_shared_buffer_drains_ring_to_buffer():
    from training.core.actor.shared_buffer import SharedBufferAdapter
    from training.core.protocols import CollectorOutput, Transition

    class _MockBuffer:
        capacity = 100

        def __init__(self):
            self.items = []

        def push(self, x):
            self.items.append(x)

        def sample(self, n, rng=None):
            raise NotImplementedError

        def clear(self):
            self.items.clear()

        def __len__(self):
            return len(self.items)

        def state_dict(self):
            return {}

        def load_state_dict(self, sd):
            pass

    ring = SHMRing(capacity=8, slot_payload_max=8192)
    # Push a raw list[Transition] (what actor_main sends)
    t = Transition(obs=None, action=0, legal_mask=None, reward=0.0, done=True, payload={})
    ring.push([t, t])
    # Push a CollectorOutput (what paradigm adapter might send)
    ring.push(CollectorOutput(transitions=[t], episode_stats=[]))

    buf = _MockBuffer()
    adapter = SharedBufferAdapter(ring, buf)
    n = adapter.drain(max_items=10)
    assert n == 2
    assert len(buf.items) == 2
    assert isinstance(buf.items[0], CollectorOutput)
    assert isinstance(buf.items[1], CollectorOutput)
    adapter.close()
