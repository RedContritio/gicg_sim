"""AZAsyncCollector unit tests (I31 #88 AZ T2, B').

Mock-light surface tests: a fake InferenceServer / InferenceClient (records its
wiring calls) + a fake eval net + a real TrainingConfig. We exercise the API
surface — server stand-up + actor handoff (publish-then-spawn ordering, the B'
actor_kwargs contract), ring drain of ``_AZRunnerOutput``, sync_weights →
server.push_weights, close teardown order, state_dict roundtrip — WITHOUT
spawning real processes. The mp builders themselves are covered in
``test_az_mp_factories.py``; the real-spawn end-to-end (InferenceServer +
GicgEnv + DSL) lives in the T7 smoke_full suite.

Unlike DMC/PPO, AZ keeps weights server-side (no WeightsSHM publish): the tests
assert the (mock) Runtime is NEVER asked to ``publish_weights``.
"""

from __future__ import annotations

import pytest

from training.paradigms.az.config import AZParadigmConfig


# ---------- Test doubles ---------- #


class _MockRuntime:
    def __init__(self):
        self.published: list = []
        self.start_actors_calls: list = []
        self.closed = False
        self._procs: list = []

    def publish_weights(self, state_dict, version: int, tag: str = 'latest'):
        # AZ should NEVER call this (weights live server-side) — recorded so a
        # regression that reintroduces a WeightsSHM publish fails the assertion.
        self.published.append((version, len(state_dict)))

    def start_actors(self, n_actors: int, actor_kwargs_factory=None, actor_kwargs=None):
        kw = actor_kwargs_factory(0) if actor_kwargs_factory is not None else actor_kwargs
        self.start_actors_calls.append((n_actors, kw))
        self._procs = [_FakeProc(alive=True) for _ in range(n_actors)]
        return list(self._procs)

    def actor_procs(self):
        return list(self._procs)

    def close(self):
        self.closed = True


class _FakeProc:
    def __init__(self, alive: bool):
        self._alive = alive

    def is_alive(self) -> bool:
        return self._alive


class _MockRing:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.closed = False

    def try_pop(self):
        return self.items.pop(0) if self.items else None

    def close(self):
        self.closed = True


class _FakeNet:
    """Eval net stub — only ``.net.state_dict()`` is touched (by
    ``_cpu_net_state_dict`` when pushing weights to the server)."""

    def __init__(self):
        import torch.nn as nn

        self.net = nn.Linear(4, 3)


class _FakeServer:
    """Records the InferenceServer wiring without spawning a process."""

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.started = False
        self.pushed: list = []
        self.stopped = False
        self._pipes: dict = {}
        self._stats_queue = object()

    def start(self, *a, **k):
        self.started = True

    def push_weights(self, cpu_state_dict):
        if not self.started:
            raise RuntimeError('push_weights before start')
        self.pushed.append(cpu_state_dict)

    def get_worker_pipe(self, worker_id: int):
        pipe = ('pipe', worker_id)
        self._pipes[worker_id] = pipe
        return pipe

    @property
    def stats_queue(self):
        return self._stats_queue

    def stop(self, *a, **k):
        self.stopped = True


class _FakeClient:
    def __init__(self, worker_id: int, pipe):
        self.worker_id = worker_id
        self.pipe = pipe


def _real_cfg(num_actors: int = 2):
    """Real TrainingConfig with a tiny AZ agent shape (cheap to build, lets
    ``_agent_config`` derive a real AgentConfig)."""
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    return TrainingConfig(
        meta=MetaCfg(seed=7, paradigm='az', run_label='t', device='cpu'),
        pipeline=PipelineCfg(mode='async', num_actors=num_actors),
        scenario=ScenarioCfg(team_0=['赤蝶'], team_1=['赤蝶'], pool=['v_legacy', 'test_basic']),
        paradigm={
            'agent': {
                'n_counter_slots': 8,
                'n_hooks': 4,
                'max_ops_per_hook': 4,
                'max_actions': 8,
                'd_model': 8,
                'n_cross_layers': 1,
            },
            'mcts': {'n_rollouts': 4, 'profile': False},
        },
        checkpoint=CheckpointCfg(),
    )


def _pcfg(cfg):
    return AZParadigmConfig.from_dict(cfg.paradigm)


def _stub_runner_output(n_steps: int, winner: int = 0, game_static=None):
    """A ring item as the actor pushes it (push_episode_record=True): an
    ``_AZRunnerOutput`` carrying a ``SelfPlayResult``."""
    import numpy as np

    from training.paradigms.az.mp_factories import _AZRunnerOutput
    from training.paradigms.az.selfplay import SelfPlayResult

    sp = SelfPlayResult(
        game_static=game_static if game_static is not None else {'gs': winner},
        steps=[{'pi_target': np.zeros(3, dtype=np.float32)} for _ in range(n_steps)],
        winner=winner,
        n_steps=n_steps,
        discovery_count=0,
    )
    return _AZRunnerOutput(transitions=[], selfplay_result=sp)


# ---------- Tests ---------- #


def test_az_async_collector_import_surface():
    """Public re-export holds (paradigm.py imports AZAsyncCollector)."""
    from training.paradigms.az.collector import AZAsyncCollector, AZSelfPlayCollector

    assert AZAsyncCollector is not None
    assert AZSelfPlayCollector is not None
    # No-arg ctor must fail on missing positional args (not a placeholder).
    with pytest.raises(TypeError):
        AZAsyncCollector()


def test_az_async_collector_bootstrap_starts_server_then_spawns(monkeypatch):
    """_bootstrap stands up the shared InferenceServer (start → push initial
    weights), attaches N clients, then spawns actors with the B' actor_kwargs:
    mp_factories dotted paths + AB14 episode_runner_factory_path +
    push_episode_record=True + per-actor inference_client. Weights live
    server-side — the Runtime is never asked to publish_weights."""
    import training.core.inference.client as cli_mod
    import training.core.inference.server as srv_mod

    created: dict = {}

    def _make_server(**kwargs):
        srv = _FakeServer(**kwargs)
        created['server'] = srv
        return srv

    monkeypatch.setattr(srv_mod, 'InferenceServer', _make_server)
    monkeypatch.setattr(cli_mod, 'InferenceClient', _FakeClient)

    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    cfg = _real_cfg(num_actors=2)
    coll = AZAsyncCollector(cfg, _pcfg(cfg), _FakeNet(), runtime=rt, ring=_MockRing())

    assert not rt.start_actors_calls
    coll._bootstrap()

    srv = created['server']
    # Server constructed with the AZ-specific factory + handler paths.
    assert srv.kwargs['n_workers'] == 2
    assert srv.kwargs['network_factory_path'] == 'training.paradigms.az.network.Agent'
    assert srv.kwargs['inference_handlers_module_path'] == 'training.paradigms.az._inference_handlers'
    # agent_config derived from the ObsShape (paradigm.agent).
    assert srv.kwargs['agent_config'].max_actions == 8
    assert srv.kwargs['agent_config'].n_counter_slots == 8
    # start happened, then initial weights pushed (ordering: push requires start).
    assert srv.started is True
    assert len(srv.pushed) == 1
    # One client per actor, wired to the server pipes.
    assert len(coll._inference_clients) == 2

    # B' actor_kwargs contract.
    assert len(rt.start_actors_calls) == 1
    n_actors, kw = rt.start_actors_calls[0]
    assert n_actors == 2
    mp = 'training.paradigms.az.mp_factories'
    assert kw['build_env_factory_path'] == f'{mp}.build_az_env_factory'
    assert kw['build_opp_registry_path'] == f'{mp}.build_az_opp_registry'
    assert kw['build_policy_path'] == f'{mp}.build_az_policy'
    assert kw['build_provider_path'] == f'{mp}.build_az_provider'
    assert kw['spec_sampler_path'] == f'{mp}.az_spec_sampler'
    assert kw['episode_runner_factory_path'] == f'{mp}.build_az_selfplay_runner'
    assert kw['push_episode_record'] is True
    assert kw['transition_queue'] is coll.ring
    assert 'inference_client' in kw and kw['inference_client'] is not None
    # AZ keeps weights server-side — Runtime.publish_weights must NOT be used.
    assert rt.published == []

    # Idempotent — second call must not re-spawn.
    coll._bootstrap()
    assert len(rt.start_actors_calls) == 1


def test_az_async_collector_collect_drains_ring():
    from training.paradigms.az.collector import AZAsyncCollector

    items = [_stub_runner_output(3, winner=0, game_static={'a': 1}), _stub_runner_output(2, winner=1)]
    rt = _MockRuntime()
    ring = _MockRing(items=list(items))
    coll = AZAsyncCollector(cfg=_real_cfg(), paradigm_cfg=None, network=_FakeNet(), runtime=rt, ring=ring)
    coll._spawned = True  # skip _bootstrap (no server stand-up needed to drain)

    out = coll.collect(n_episodes=10, provider=None)
    assert out.n_units == 5  # 3 + 2 steps
    assert len(out.episode_stats) == 2
    assert out.runtime_metrics['n_pulled'] == 2
    # (game_static, steps) tuples — same shape as serial AZSelfPlayCollector.
    trajs = out.runtime_metrics['az_trajectories']
    assert trajs[0][0] == {'a': 1}
    assert len(trajs[0][1]) == 3
    assert len(trajs[1][1]) == 2
    # episode_stats carry winner + n_steps from the SelfPlayResult.
    assert out.episode_stats[0]['winner'] == 0 and out.episode_stats[0]['n_steps'] == 3
    assert out.episode_stats[1]['winner'] == 1 and out.episode_stats[1]['source'] == 'mp_actor'

    # Empty ring → 0 units; no re-spawn.
    out2 = coll.collect(n_episodes=10, provider=None)
    assert out2.n_units == 0
    assert len(rt.start_actors_calls) == 0  # _spawned was forced True


def test_az_async_collector_collect_respects_max_pull():
    from training.paradigms.az.collector import AZAsyncCollector

    items = [_stub_runner_output(1, winner=i % 2) for i in range(4)]
    coll = AZAsyncCollector(
        cfg=_real_cfg(), paradigm_cfg=None, network=_FakeNet(), runtime=_MockRuntime(), ring=_MockRing(items=items)
    )
    coll._spawned = True
    out = coll.collect(n_episodes=2, provider=None)
    assert out.runtime_metrics['n_pulled'] == 2


def test_az_async_collector_sync_weights_bumps_version_no_server():
    """Before _bootstrap there's no server — sync_weights just bumps the
    version counter (push is skipped) and never touches WeightsSHM."""
    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    coll = AZAsyncCollector(cfg=_real_cfg(), paradigm_cfg=None, network=_FakeNet(), runtime=rt, ring=_MockRing())
    v1 = coll.sync_weights(_FakeNet())
    v2 = coll.sync_weights(_FakeNet())
    assert v1 == 1 and v2 == 2
    assert rt.published == []  # no WeightsSHM publish


def test_az_async_collector_sync_weights_pushes_to_server(monkeypatch):
    """After _bootstrap, sync_weights pushes the learner net's params to the
    InferenceServer (server owns the weights). paradigm_cfg=None here also
    exercises the _agent_config fallback (reconstruct from cfg.paradigm dict)."""
    import training.core.inference.client as cli_mod
    import training.core.inference.server as srv_mod

    created: dict = {}

    def _make_server(**kwargs):
        srv = _FakeServer(**kwargs)
        created['server'] = srv
        return srv

    monkeypatch.setattr(srv_mod, 'InferenceServer', _make_server)
    monkeypatch.setattr(cli_mod, 'InferenceClient', _FakeClient)

    from training.paradigms.az.collector import AZAsyncCollector

    coll = AZAsyncCollector(
        cfg=_real_cfg(1), paradigm_cfg=None, network=_FakeNet(), runtime=_MockRuntime(), ring=_MockRing()
    )
    coll._bootstrap()
    srv = created['server']
    assert len(srv.pushed) == 1  # initial push (after start)
    v = coll.sync_weights(_FakeNet())
    assert v == 1
    assert len(srv.pushed) == 2  # sync pushed again
    coll.close()


def test_az_async_collector_close_idempotent():
    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    ring = _MockRing()
    coll = AZAsyncCollector(cfg=_real_cfg(), paradigm_cfg=None, network=_FakeNet(), runtime=rt, ring=ring)
    coll._spawned = True
    coll.close()
    assert rt.closed is True
    assert ring.closed is True
    assert coll._spawned is False
    # Second close must not raise.
    coll.close()


def test_az_async_collector_actors_alive_count():
    """actors_alive_count proxies Runtime.actor_procs() (used by the async
    ingest loop to detect a dead actor pool)."""
    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    coll = AZAsyncCollector(cfg=_real_cfg(), paradigm_cfg=None, network=_FakeNet(), runtime=rt, ring=_MockRing())
    assert coll.actors_alive_count() == 0  # no procs yet
    rt._procs = [_FakeProc(alive=True), _FakeProc(alive=False), _FakeProc(alive=True)]
    assert coll.actors_alive_count() == 2


def test_az_async_collector_state_dict_roundtrip():
    from training.paradigms.az.collector import AZAsyncCollector

    coll = AZAsyncCollector(
        cfg=_real_cfg(),
        paradigm_cfg=None,
        network=_FakeNet(),
        runtime=_MockRuntime(),
        ring=_MockRing(items=[_stub_runner_output(1), _stub_runner_output(1)]),
    )
    coll._spawned = True
    coll.collect(n_episodes=2, provider=None)
    coll.sync_weights(_FakeNet())
    sd = coll.state_dict()
    assert sd['episode_seq'] == 2
    assert sd['weights_version'] == 1
    assert sd['master_seed'] == 7

    coll2 = AZAsyncCollector(
        cfg=_real_cfg(), paradigm_cfg=None, network=_FakeNet(), runtime=_MockRuntime(), ring=_MockRing()
    )
    coll2.load_state_dict(sd)
    assert coll2._episode_seq == 2
    assert coll2._weights_version == 1


def test_az_async_collector_paradigm_dispatch_async_mode():
    """AZParadigm.make_collector(mode='async') routes to AZAsyncCollector
    (real network, no spawn — just type check + close)."""
    from dataclasses import replace

    from training.paradigms.az import AZParadigm
    from training.paradigms.az.collector import AZAsyncCollector

    cfg = _real_cfg(num_actors=1)
    cfg_async = replace(cfg, pipeline=replace(cfg.pipeline, mode='async'))
    p = AZParadigm()
    net = p.make_network(cfg_async)
    coll = p.make_collector(cfg_async, env_factory=lambda i: None, network=net, opp_pool=None)
    assert isinstance(coll, AZAsyncCollector)
    # Tear down owned Runtime + ring SHM so they don't leak.
    coll.close()
