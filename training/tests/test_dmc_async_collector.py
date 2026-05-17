"""DMCAsyncCollector / DMCMultiProcessCollector unit tests (FU-W3b-DMC).

These tests inject mocked Runtime + SHMRing so we exercise the API
surface (publish-before-spawn, drain, sync_weights, close, state_dict)
without spawning real processes. Real-mp validation lives in
`test_core_actor_mp.py` (Runtime / WeightsSHM / SHMRing in isolation).

Out-of-scope here: end-to-end DMC mp episode play — that requires DMC
migration from legacy `play_one_episode` (DmcAgent static obs cache)
to the typed `EpisodePolicy`. The task spec for FU-W3b-DMC explicitly
contracts the API surface only, with a mock-Runtime test plan.
"""

from __future__ import annotations

import pytest


# ---------- Test doubles ---------- #


class _MockRuntime:
    def __init__(self):
        self.published: list = []
        self.start_actors_calls: list = []
        self.closed = False

    def publish_weights(self, state_dict, version: int, tag: str = 'latest'):
        self.published.append((version, len(state_dict)))

    def start_actors(self, n_actors: int, actor_kwargs_factory=None, actor_kwargs=None):
        kw = actor_kwargs_factory(0) if actor_kwargs_factory is not None else actor_kwargs
        self.start_actors_calls.append((n_actors, kw))
        return [object()] * n_actors

    def close(self):
        self.closed = True


class _MockRing:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.closed = False

    def try_pop(self):
        return self.items.pop(0) if self.items else None

    def close(self):
        self.closed = True


def _tiny_net():
    import torch.nn as nn

    return nn.Linear(4, 3)


def _async_cfg_obj():
    """Minimal duck-typed cfg for the mp collector (avoids loading a
    real TOML — keeps test xdist-safe + fast)."""

    class _Meta:
        seed = 7

    class _Pipeline:
        num_actors = 2

    class _Cfg:
        meta = _Meta()
        pipeline = _Pipeline()
        paradigm = {}

    return _Cfg()


# ---------- Tests ---------- #


def test_dmc_async_collector_alias():
    from training.paradigms.dmc.collector import DMCAsyncCollector, DMCMultiProcessCollector

    assert DMCAsyncCollector is DMCMultiProcessCollector


def test_dmc_async_collector_import_surface():
    """Public re-export holds (paradigm.py imports DMCMultiProcessCollector)."""
    from training.paradigms.dmc import DMCAsyncCollector, DMCMultiProcessCollector, DMCSerialCollector

    assert DMCMultiProcessCollector is not None
    assert DMCAsyncCollector is DMCMultiProcessCollector
    assert DMCSerialCollector is not None


def test_dmc_async_collector_bootstrap_publishes_then_spawns():
    """W3a constraint: WeightsSHM.write('latest', ...) must happen before
    start_actors so child providers can attach."""
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    rt = _MockRuntime()
    ring = _MockRing()
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=rt,
        ring=ring,
    )
    # Bootstrap not done at __init__.
    assert not rt.published
    assert not rt.start_actors_calls
    coll._bootstrap()
    # Publish happened, then spawn — sequencing enforced by bootstrap body.
    assert len(rt.published) == 1
    assert rt.published[0][0] == 0  # initial version
    assert rt.start_actors_calls == [
        (
            2,
            {
                'build_env_factory_path': 'training.paradigms.dmc.collector._dmc_build_env_factory',
                'build_opp_registry_path': 'training.paradigms.dmc.collector._dmc_build_opp_registry',
                'build_policy_path': 'training.paradigms.dmc.collector._dmc_build_policy',
                'build_provider_path': 'training.paradigms.dmc.collector._dmc_build_provider',
                'spec_sampler_path': 'training.paradigms.dmc.collector._dmc_spec_sampler',
                'transition_queue': ring,
            },
        ),
    ]
    # Bootstrap idempotent — second call must not re-spawn.
    coll._bootstrap()
    assert len(rt.start_actors_calls) == 1


def test_dmc_async_collector_collect_drains_ring():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    # Put a couple of "transition lists" in the ring (what actor_main pushes).
    items = [['t0a', 't0b', 't0c'], ['t1a', 't1b']]
    rt = _MockRuntime()
    ring = _MockRing(items=list(items))
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=rt,
        ring=ring,
    )
    out = coll.collect(n_episodes=10, provider=None)
    assert out.n_units == 5  # 3 + 2 transitions
    assert len(out.episode_stats) == 2
    assert out.runtime_metrics['n_pulled'] == 2
    assert out.runtime_metrics['dmc_episodes'][0][0] == items[0]
    # Subsequent collect with empty ring → 0 units, runtime not re-spawned.
    out2 = coll.collect(n_episodes=10, provider=None)
    assert out2.n_units == 0
    assert len(rt.start_actors_calls) == 1


def test_dmc_async_collector_collect_respects_max_pull():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    items = [['a'], ['b'], ['c'], ['d']]
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(items=list(items)),
    )
    out = coll.collect(n_episodes=2, provider=None)
    assert out.runtime_metrics['n_pulled'] == 2  # capped by n_episodes


def test_dmc_async_collector_sync_weights_bumps_version():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    rt = _MockRuntime()
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=rt,
        ring=_MockRing(),
    )
    v1 = coll.sync_weights(_tiny_net())
    v2 = coll.sync_weights(_tiny_net())
    assert v1 == 1
    assert v2 == 2
    assert len(rt.published) == 2
    assert rt.published[0][0] == 1
    assert rt.published[1][0] == 2


def test_dmc_async_collector_close_idempotent():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    rt = _MockRuntime()
    ring = _MockRing()
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=rt,
        ring=ring,
    )
    coll._bootstrap()
    coll.close()
    assert rt.closed is True
    assert ring.closed is True
    # Second close must not raise.
    coll.close()


def test_dmc_async_collector_state_dict_roundtrip():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(items=[['a'], ['b']]),
    )
    coll.collect(n_episodes=2, provider=None)
    coll.sync_weights(_tiny_net())
    sd = coll.state_dict()
    assert sd['episode_seq'] == 2
    assert sd['weights_version'] == 1
    assert sd['master_seed'] == 7

    coll2 = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(),
    )
    coll2.load_state_dict(sd)
    assert coll2._episode_seq == 2
    assert coll2._weights_version == 1


def test_dmc_async_collector_paradigm_dispatch_async_mode():
    """Verify paradigm.make_collector(mode='async') routes to MP class
    (smoke — without spawning, since we only confirm the type)."""
    from dataclasses import replace

    from training.core.config.loader import load_cfg
    from training.paradigms import resolve
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    # cfg-toml-restructure-paradigm-scoped: archived legacy flat toml no longer
    # loads (CC-301 hard break). Routed to current hybrid smoke cfg.
    cfg = load_cfg('configs/dmc/smoke.toml')
    cfg_async = replace(cfg, pipeline=replace(cfg.pipeline, mode='async'))
    p = resolve('dmc')
    net = p.make_network(cfg_async)
    opp_pool = p.make_opponent_pool(cfg_async, net)
    coll = p.make_collector(cfg_async, env_factory=lambda i: None, network=net, opp_pool=opp_pool)
    assert isinstance(coll, DMCMultiProcessCollector)
    # Tear down owned Runtime + ring SHM so they don't leak.
    coll.close()


def test_dmc_async_collector_spawn_builder_missing_path_raises():
    """When `cfg.paradigm.mp_*_path` is not set, per-child builder bridges
    must raise loudly (CS4 strict)."""
    from training.paradigms.dmc.collector import (
        _dmc_build_env_factory,
        _dmc_build_opp_registry,
        _dmc_build_provider,
    )

    cfg = _async_cfg_obj()
    with pytest.raises(ValueError, match='mp_env_factory_path'):
        _dmc_build_env_factory(cfg, seed=0)
    with pytest.raises(ValueError, match='mp_opp_registry_path'):
        _dmc_build_opp_registry(cfg)
    with pytest.raises(ValueError, match='mp_provider_path'):
        _dmc_build_provider(cfg, actor_id=0)


def test_dmc_async_collector_spec_sampler_advances_per_call():
    """`_dmc_spec_sampler` must produce a fresh (monotonic) scenario_seed
    every call for the same actor_id."""
    from training.paradigms.dmc.collector import _dmc_spec_sampler

    cfg = _async_cfg_obj()
    s1 = _dmc_spec_sampler(cfg, actor_id=99)
    s2 = _dmc_spec_sampler(cfg, actor_id=99)
    assert s1.scenario_seed != s2.scenario_seed
    assert s1.opponent_id == 'random'


def test_dmc_async_collector_build_policy_returns_DMCEpisodePolicy():
    from training.paradigms.dmc.collector import _dmc_build_policy
    from training.paradigms.dmc.policy import DMCEpisodePolicy

    cfg = _async_cfg_obj()
    pol = _dmc_build_policy(cfg, actor_id=3)
    assert isinstance(pol, DMCEpisodePolicy)
    assert pol.deterministic is False
