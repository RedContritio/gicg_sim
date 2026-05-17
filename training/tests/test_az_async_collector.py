"""AZAsyncCollector unit tests (FU-W3b-AZ).

These tests inject mocked Runtime + SHMRing so we exercise the API
surface (publish-before-spawn, drain, sync_weights, close, state_dict)
without spawning real processes. Real-mp validation lives in
``test_core_actor_mp.py`` (Runtime / WeightsSHM / SHMRing in isolation).

Mirror of ``test_dmc_async_collector.py`` — same pattern, AZ-specific
spec_sampler opponent_id='self' + dotted-path builders rooted at
``training.paradigms.az.collector``.

Out-of-scope here: end-to-end AZ mp episode play — that requires AZ
migration from legacy ``play_self_game`` (Agent static-obs cache +
two-sided pi/z capture) to the typed ``EpisodePolicy``. The task spec
for FU-W3b-AZ explicitly contracts the API surface only.
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


def test_az_async_collector_import_surface():
    """Public re-export holds (paradigm.py imports AZAsyncCollector;
    previous ``raise NotImplementedError`` ctor replaced)."""
    from training.paradigms.az.collector import AZAsyncCollector, AZSelfPlayCollector

    assert AZAsyncCollector is not None
    assert AZSelfPlayCollector is not None
    # Must NOT be a placeholder anymore — no-arg ctor should fail on
    # missing positional args (TypeError), not NotImplementedError.
    with pytest.raises(TypeError):
        AZAsyncCollector()


def test_az_async_collector_bootstrap_publishes_then_spawns():
    """W3a constraint: WeightsSHM.write('latest', ...) must happen before
    start_actors so child providers can attach."""
    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    ring = _MockRing()
    coll = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
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
                'build_env_factory_path': 'training.paradigms.az.collector._az_build_env_factory',
                'build_opp_registry_path': 'training.paradigms.az.collector._az_build_opp_registry',
                'build_policy_path': 'training.paradigms.az.collector._az_build_policy',
                'build_provider_path': 'training.paradigms.az.collector._az_build_provider',
                'spec_sampler_path': 'training.paradigms.az.collector._az_spec_sampler',
                'transition_queue': ring,
            },
        ),
    ]
    # Bootstrap idempotent — second call must not re-spawn.
    coll._bootstrap()
    assert len(rt.start_actors_calls) == 1


def test_az_async_collector_collect_drains_ring():
    from training.paradigms.az.collector import AZAsyncCollector

    items = [['t0a', 't0b', 't0c'], ['t1a', 't1b']]
    rt = _MockRuntime()
    ring = _MockRing(items=list(items))
    coll = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        env_factory=None,
        runtime=rt,
        ring=ring,
    )
    out = coll.collect(n_episodes=10, provider=None)
    assert out.n_units == 5
    assert len(out.episode_stats) == 2
    assert out.runtime_metrics['n_pulled'] == 2
    # AZ shape: (game_static, transitions) tuples; game_static is None until
    # migration off play_self_game lands a typed EpisodeRunner path.
    trajs = out.runtime_metrics['az_trajectories']
    assert trajs[0][1] == items[0]
    assert trajs[1][1] == items[1]
    # Empty ring → 0 units; no re-spawn.
    out2 = coll.collect(n_episodes=10, provider=None)
    assert out2.n_units == 0
    assert len(rt.start_actors_calls) == 1


def test_az_async_collector_collect_respects_max_pull():
    from training.paradigms.az.collector import AZAsyncCollector

    items = [['a'], ['b'], ['c'], ['d']]
    coll = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(items=list(items)),
    )
    out = coll.collect(n_episodes=2, provider=None)
    assert out.runtime_metrics['n_pulled'] == 2


def test_az_async_collector_sync_weights_bumps_version():
    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    coll = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
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


def test_az_async_collector_close_idempotent():
    from training.paradigms.az.collector import AZAsyncCollector

    rt = _MockRuntime()
    ring = _MockRing()
    coll = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
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


def test_az_async_collector_state_dict_roundtrip():
    from training.paradigms.az.collector import AZAsyncCollector

    coll = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
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

    coll2 = AZAsyncCollector(
        cfg=_async_cfg_obj(),
        paradigm_cfg=None,
        network=_tiny_net(),
        env_factory=None,
        runtime=_MockRuntime(),
        ring=_MockRing(),
    )
    coll2.load_state_dict(sd)
    assert coll2._episode_seq == 2
    assert coll2._weights_version == 1


def test_az_async_collector_paradigm_dispatch_async_mode():
    """Verify AZParadigm.make_collector(mode='async') routes to
    AZAsyncCollector (smoke — no real spawn, just type check + close)."""
    from dataclasses import replace

    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )
    from training.paradigms.az import AZParadigm
    from training.paradigms.az.collector import AZAsyncCollector

    cfg = TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='t', device='cpu'),
        pipeline=PipelineCfg(mode='async', num_actors=1),
        scenario=ScenarioCfg(team_0=['赤蝶'], team_1=['赤蝶'], pool=['v_legacy', 'test_basic']),
        paradigm={
            'agent': {
                'n_counter_slots': 8,
                'n_hooks': 4,
                'max_tokens_per_hook': 4,
                'max_actions': 8,
                'd_model': 8,
                'n_cross_layers': 1,
            },
            'mcts': {'n_rollouts': 4, 'profile': False},
        },
        checkpoint=CheckpointCfg(),
    )
    cfg_async = replace(cfg, pipeline=replace(cfg.pipeline, mode='async'))
    p = AZParadigm()
    net = p.make_network(cfg_async)
    coll = p.make_collector(cfg_async, env_factory=lambda i: None, network=net, opp_pool=None)
    assert isinstance(coll, AZAsyncCollector)
    # Tear down owned Runtime + ring SHM so they don't leak.
    coll.close()


def test_az_async_collector_spawn_builder_missing_path_raises():
    """When ``cfg.paradigm.mp_*_path`` is not set, per-child builder bridges
    must raise loudly (CS4 strict)."""
    from training.paradigms.az.collector import (
        _az_build_env_factory,
        _az_build_opp_registry,
        _az_build_provider,
    )

    cfg = _async_cfg_obj()
    with pytest.raises(ValueError, match='mp_env_factory_path'):
        _az_build_env_factory(cfg, seed=0)
    with pytest.raises(ValueError, match='mp_opp_registry_path'):
        _az_build_opp_registry(cfg)
    with pytest.raises(ValueError, match='mp_provider_path'):
        _az_build_provider(cfg, actor_id=0)


def test_az_async_collector_spec_sampler_advances_per_call():
    """``_az_spec_sampler`` must produce a fresh (monotonic) scenario_seed
    every call for the same actor_id. opponent_id is 'self' per A5.2
    (self-play shares network)."""
    from training.paradigms.az.collector import _az_spec_sampler

    cfg = _async_cfg_obj()
    s1 = _az_spec_sampler(cfg, actor_id=99)
    s2 = _az_spec_sampler(cfg, actor_id=99)
    assert s1.scenario_seed != s2.scenario_seed
    assert s1.opponent_id == 'self'


def test_az_async_collector_build_policy_returns_AZEpisodePolicy():
    """``_az_build_policy`` constructs an AZEpisodePolicy with mcts_cfg +
    card_pool_spec wired from cfg (object-construction surface)."""
    from training.paradigms.az.collector import _az_build_policy
    from training.paradigms.az.policy import AZEpisodePolicy

    # Real cfg needed for resolve_pool_refs + AZParadigmConfig.from_dict.
    from training.core.config.base import (
        CheckpointCfg,
        MetaCfg,
        PipelineCfg,
        ScenarioCfg,
        TrainingConfig,
    )

    cfg = TrainingConfig(
        meta=MetaCfg(seed=42, paradigm='az', run_label='t', device='cpu'),
        pipeline=PipelineCfg(mode='async', num_actors=1),
        scenario=ScenarioCfg(team_0=['赤蝶'], team_1=['赤蝶'], pool=['v_legacy', 'test_basic']),
        paradigm={
            'agent': {
                'n_counter_slots': 8,
                'n_hooks': 4,
                'max_tokens_per_hook': 4,
                'max_actions': 8,
                'd_model': 8,
                'n_cross_layers': 1,
            },
            'mcts': {'n_rollouts': 4, 'profile': False},
        },
        checkpoint=CheckpointCfg(),
    )
    pol = _az_build_policy(cfg, actor_id=3)
    assert isinstance(pol, AZEpisodePolicy)
    assert pol.deterministic is False
    # Spec A1.2: MCTS cfg must be wired (act() needs it).
    assert pol.mcts_cfg is not None
    # Spec A1.3: card_pool_spec needed for determinization.
    assert pol.card_pool_spec is not None
