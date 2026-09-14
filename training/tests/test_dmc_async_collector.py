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
    start_actors so child providers can attach.

    Post P2-PoC E wiring: bootstrap also stands up a real
    InferenceServer + per-actor InferenceClient. We mock the runtime
    (no real actor spawn) but the server IS spawned because the mp
    factories require an attached client. ``close()`` shuts everything
    down in order.
    """
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
    try:
        coll._bootstrap()
        # Publish happened, then spawn — sequencing enforced by bootstrap body.
        assert len(rt.published) == 1
        assert rt.published[0][0] == 0  # initial version
        # Single start_actors call with the expected dotted paths +
        # inference_client kwarg threaded through.
        assert len(rt.start_actors_calls) == 1
        n_actors, kwargs = rt.start_actors_calls[0]
        assert n_actors == 2
        assert kwargs['build_env_factory_path'] == 'training.paradigms.dmc.mp_factories.build_dmc_env_factory'
        assert kwargs['build_opp_registry_path'] == 'training.paradigms.dmc.mp_factories.build_dmc_opp_registry'
        assert kwargs['build_policy_path'] == 'training.paradigms.dmc.collector._dmc_build_policy'
        assert kwargs['build_provider_path'] == 'training.paradigms.dmc.mp_factories.build_dmc_provider'
        assert kwargs['spec_sampler_path'] == 'training.paradigms.dmc.collector._dmc_spec_sampler'
        assert kwargs['transition_queue'] is ring
        # Per-actor InferenceClient registered + threaded into kwargs.
        assert 'inference_client' in kwargs
        assert kwargs['inference_client'] is not None
        # Bootstrap idempotent — second call must not re-spawn.
        coll._bootstrap()
        assert len(rt.start_actors_calls) == 1
    finally:
        coll.close()


def _stub_episode(n_trans: int, winner: int = 0, action_base: int = 0, scenario_seed: int = 12345):
    """Build a minimal EpisodeRecord ring item: list[Transition] + winner.

    Each Transition payload carries ``dmc_obs_dict`` (the only payload key
    :func:`_adapt_episode_record` consumes). Obs payload is a sentinel
    string — the adapter doesn't introspect contents, only presence.
    """
    from training.core.protocols import EpisodeRecord, Transition

    trans = [
        Transition(
            obs=None,
            action=action_base + i,
            legal_mask=None,
            reward=0.0,
            done=(i == n_trans - 1),
            payload={'dmc_obs_dict': f'obs_{action_base + i}'},
        )
        for i in range(n_trans)
    ]
    return EpisodeRecord(
        transitions=trans,
        final_reward=0.0,
        length=n_trans,
        winner=winner,
        opponent_id='random',
        scenario_seed=scenario_seed,
    )


def test_dmc_async_collector_collect_drains_ring():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    # Ring items are EpisodeRecord (post mp-provider type-mismatch fix).
    items = [
        _stub_episode(3, winner=0, scenario_seed=98765),
        _stub_episode(2, winner=1, action_base=10, scenario_seed=12345),
    ]
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
    try:
        out = coll.collect(n_episodes=10, provider=None)
        assert out.n_units == 5  # 3 + 2 transitions
        assert len(out.episode_stats) == 2
        assert [stat['scenario_seed'] for stat in out.episode_stats] == [98765, 12345]
        assert all('seeds' not in stat for stat in out.episode_stats)
        assert out.runtime_metrics['n_pulled'] == 2
        assert out.runtime_metrics['n_dropped'] == 0
        # First episode (winner=0, our_player=0) → G=+1; second → G=-1.
        eps = out.runtime_metrics['dmc_episodes']
        assert len(eps) == 2
        assert eps[0][1] == 1.0
        assert eps[1][1] == -1.0
        assert len(eps[0][0]) == 3
        # DmcTransition carries action_idx + obs_dict pulled from payload.
        assert eps[0][0][0].action_idx == 0
        assert eps[0][0][0].obs_dict == 'obs_0'
        # Subsequent collect with empty ring → 0 units, runtime not re-spawned.
        out2 = coll.collect(n_episodes=10, provider=None)
        assert out2.n_units == 0
        assert len(rt.start_actors_calls) == 1
    finally:
        coll.close()


def test_dmc_async_collector_collect_respects_max_pull():
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    items = [_stub_episode(1, action_base=i) for i in range(4)]
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(items=list(items)),
    )
    try:
        out = coll.collect(n_episodes=2, provider=None)
        assert out.runtime_metrics['n_pulled'] == 2  # capped by n_episodes
    finally:
        coll.close()


def test_dmc_async_collector_collect_drops_missing_obs():
    """Transitions without payload['dmc_obs_dict'] are dropped (defensive)."""
    from training.core.protocols import EpisodeRecord, Transition
    from training.paradigms.dmc.collector import DMCMultiProcessCollector

    # 1 good + 1 bad transition in a single episode.
    bad = EpisodeRecord(
        transitions=[
            Transition(obs=None, action=0, legal_mask=None, reward=0.0, done=False, payload={'dmc_obs_dict': 'good'}),
            Transition(
                obs=None, action=1, legal_mask=None, reward=0.0, done=True, payload={}
            ),  # missing obs_dict → drop
        ],
        final_reward=0.0,
        length=2,
        winner=0,
        opponent_id='random',
        scenario_seed=12345,
    )
    coll = DMCMultiProcessCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        opp_pool=None,
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(items=[bad]),
    )
    try:
        out = coll.collect(n_episodes=1, provider=None)
        assert out.n_units == 1
        assert out.runtime_metrics['n_dropped'] == 1
        assert out.episode_stats[0]['n_dropped'] == 1
    finally:
        coll.close()


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
        ring=_MockRing(items=[_stub_episode(0, winner=2), _stub_episode(0, winner=2)]),
    )
    try:
        coll.collect(n_episodes=2, provider=None)
        coll.sync_weights(_tiny_net())
        sd = coll.state_dict()
        assert sd['episode_seq'] == 2
        assert sd['weights_version'] == 1
        assert sd['master_seed'] == 7
    finally:
        coll.close()

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
