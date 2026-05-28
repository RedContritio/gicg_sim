"""Unit tests for PPOAsyncCollector (FU-W3b-PPO 真 mp 接通)。

Split from test_ppo_paradigm.py for line-limit hook compliance。Mock-only
(no GicgEnv / no real spawn) — end-to-end smoke 在 test_ppo_async_mp_e2e.py
(smoke_full marker, opt-in)。

Post 2026-05-29 cleanup (I31 backlog #88):builders + provider class moved
to ``training.paradigms.ppo.mp_factories``;spawn handoff via AB13
``provider_kwargs`` (was env-var bridge ``_ENV_OPPONENT`` / ``_ENV_SHM_PATH``
/ ``_ENV_NET_PATH``, now deleted)。
"""

from __future__ import annotations

import pytest

from training.paradigms.ppo.config import PPOParadigmConfig
from training.paradigms.ppo.network import PPONetwork


class _AsyncCfg:
    """Minimal cfg stub(避开 TOML load + GicgEnv 触碰)。

    Post-cleanup:``paradigm.rollout.rollout_opponent`` 走 cfg dict
    (不再通过 env var bridge),test 直接 set 字段值。"""

    paradigm = {'gamma': 0.95, 'gae_lambda': 0.9, 'rollout': {'rollout_opponent': 'random'}}

    class pipeline:
        mode = 'async'
        num_actors = 2

    class meta:
        seed = 7


class _AsyncCfgSelfOpp:
    """Variant with rollout_opponent='self' (frozen tier should退化 to 'random')。"""

    paradigm = {'gamma': 0.95, 'gae_lambda': 0.9, 'rollout': {'rollout_opponent': 'self'}}

    class pipeline:
        mode = 'async'
        num_actors = 2

    class meta:
        seed = 7


def test_ppo_async_collector_importable_and_re_exported():
    """import surface(collector re-export + sibling 同一类)。"""
    from training.paradigms.ppo._async import PPOAsyncCollector as A1
    from training.paradigms.ppo.collector import PPOAsyncCollector as A2

    assert A1 is A2 and A1.requires_network_in_collect is True


def test_ppo_async_build_policy_seed_per_actor():
    """per-actor seed 不撞 → 不同 RNG state(避免 actor 撞 action)。"""
    from training.paradigms.ppo.mp_factories import build_policy

    p0, p1 = build_policy(_AsyncCfg(), 0), build_policy(_AsyncCfg(), 1)
    assert p0.gamma == 0.95 and p0.gae_lambda == 0.9 and p0.deterministic is False
    assert p0._np_rng.bit_generator.state != p1._np_rng.bit_generator.state


def test_ppo_async_spec_sampler_monotonic_and_self_to_random():
    """spec_sampler:per-actor 单调 + opp 'self' → 'random'(frozen 不接 self-play)。

    Post-cleanup:opp_id 从 cfg.paradigm['rollout']['rollout_opponent'] 读
    (mp 子进程通过 cfg pickle 流转), 不再通过 env var bridge。
    """
    from training.paradigms.ppo.mp_factories import _SPEC_COUNTERS, spec_sampler

    # Default rollout_opponent='random' → opp_id stays 'random'
    _SPEC_COUNTERS.clear()
    s0 = spec_sampler(_AsyncCfg(), actor_id=0)
    s1 = spec_sampler(_AsyncCfg(), actor_id=0)
    s2 = spec_sampler(_AsyncCfg(), actor_id=1)
    assert s0.scenario_seed != s1.scenario_seed != s2.scenario_seed
    assert s0.opponent_id == 'random'

    # rollout_opponent='self' → 退化到 'random' (frozen tier)
    _SPEC_COUNTERS.clear()
    s3 = spec_sampler(_AsyncCfgSelfOpp(), actor_id=0)
    assert s3.opponent_id == 'random', f"'self' should degrade to 'random', got {s3.opponent_id}"


def test_ppo_async_provider_wraps_local_and_shm():
    """_PPOActorProvider:forward 委托 + SHM 新 version → load,旧 / cold → skip。"""
    from training.paradigms.ppo.mp_factories import _PPOActorProvider

    class _Net:
        def __init__(self):
            self.loaded, self.load_count = None, 0

        def load_state_dict(self, sd):
            self.loaded, self.load_count = sd, self.load_count + 1

    class _Local:
        def __init__(self, ver):
            self.network, self.version = _Net(), ver

        def forward(self, obs, mask):
            return ('fwd', obs)

        def update_weights(self, version_tag=None, state_dict=None):
            if state_dict is not None:
                self.version += 1
            return self.version

        def current_version(self):
            return self.version

        def close(self):
            self.network = None

    class _SHM:
        def __init__(self, sd, ver):
            self.sd, self.ver = sd, ver

        def read(self, tag):
            return self.sd, self.ver

    # newer SHM → load + bump
    loc = _Local(ver=5)
    p = _PPOActorProvider(loc, _SHM({'w': 1.0}, ver=10))
    assert p.forward('o', None) == ('fwd', 'o')
    assert p.update_weights() == 10 and loc.version == 10 and loc.network.loaded == {'w': 1.0}
    # state_dict direct → 委托 + bump
    assert p.update_weights(state_dict={'w': 2.0}) == 11

    # SHM 同 version → 不 reload
    loc2 = _Local(ver=10)
    p2 = _PPOActorProvider(loc2, _SHM({'w': 1.0}, ver=10))
    assert p2.update_weights() == 10 and loc2.network.load_count == 0

    # SHM cold → 不 raise + 不 reload
    loc3 = _Local(ver=3)
    p3 = _PPOActorProvider(loc3, _SHM(None, ver=-1))
    assert p3.update_weights() == 3 and loc3.network.load_count == 0

    # close 委托
    p.close()
    assert loc.network is None


def test_ppo_async_provider_kwargs_handoff():
    """AB13:actor_main 走 provider_kwargs path → build_provider(cfg, actor_id, **kw)。

    Mock build_provider 验证 kwargs 透传 — 不真 spawn,in-proc actor_main 跑 1
    iteration 后 stop_event 触发 finally cleanup。 验证 build_provider 被
    call 时拿到 provider_kwargs dict 展开的 named args。
    """
    import queue as _q

    from training.core.actor.actor_process import actor_main
    from training.core.protocols import EpisodeSpec

    captured: dict = {}

    def _mock_build_provider(cfg, actor_id, *, weights_shm_info, network_blueprint_path):
        captured['cfg'] = cfg
        captured['actor_id'] = actor_id
        captured['weights_shm_info'] = weights_shm_info
        captured['network_blueprint_path'] = network_blueprint_path

        class _P:
            def forward(self, obs, mask):
                return None

            def update_weights(self):
                return 1

            def close(self):
                pass

        return _P()

    def _mock_build_env_factory(cfg, seed):
        return lambda s: None

    def _mock_build_opp_registry(cfg):
        return {}

    def _mock_build_policy(cfg, actor_id):
        return None

    def _mock_spec_sampler(cfg, actor_id):
        return EpisodeSpec(scenario_seed=0, opponent_id='random')

    # Run actor_main with should_stop=True from the start so it exits cleanly
    # after build_provider is called (before EpisodeRunner.run).
    q = _q.Queue()
    handoff = {
        'weights_shm_info': {'fake': 'shm_info'},
        'network_blueprint_path': '/tmp/fake_blueprint.pkl',
    }

    # actor_main builds provider then loops; should_stop=True immediately
    # exits loop. EpisodeRunner construction needs env_factory + opp_registry,
    # both mocked (constructor just stores them).
    # We need a real-ish EpisodeRunner — mock its run() too via the policy.

    try:
        actor_main(
            actor_id=42,
            cfg=_AsyncCfg(),
            build_env_factory=_mock_build_env_factory,
            build_opp_registry=_mock_build_opp_registry,
            build_policy=_mock_build_policy,
            build_provider=_mock_build_provider,
            spec_sampler=_mock_spec_sampler,
            transition_queue=q,
            should_stop=lambda: True,  # immediate exit
            provider_kwargs=handoff,
        )
    except Exception:
        # Should not reach run loop body, but EpisodeRunner ctor may complain
        # if env_factory returns None. We tolerate that — assertions below
        # only depend on build_provider being called.
        pass

    assert captured.get('actor_id') == 42
    assert captured.get('weights_shm_info') == {'fake': 'shm_info'}
    assert captured.get('network_blueprint_path') == '/tmp/fake_blueprint.pkl'


def test_ppo_async_provider_kwargs_inference_client_mutex():
    """AB13 mutex:provider_kwargs + inference_client 都 non-None → ValueError。"""
    import queue as _q

    from training.core.actor.actor_process import actor_main

    def _noop_builder(*args, **kwargs):
        return None

    def _noop_provider(cfg, actor_id, **kw):
        return None

    q = _q.Queue()
    with pytest.raises(ValueError, match='mutually exclusive'):
        actor_main(
            actor_id=0,
            cfg=_AsyncCfg(),
            build_env_factory=_noop_builder,
            build_opp_registry=_noop_builder,
            build_policy=_noop_builder,
            build_provider=_noop_provider,
            spec_sampler=_noop_builder,
            transition_queue=q,
            should_stop=lambda: True,
            inference_client='fake_client',
            provider_kwargs={'fake': 'kwargs'},
        )


def _make_unspawned(pcfg, q, timeout=2.0):
    """构造不 spawn 的 PPOAsyncCollector(__new__ + 手动 set);避开 mp。"""
    from training.paradigms.ppo._async import PPOAsyncCollector

    c = PPOAsyncCollector.__new__(PPOAsyncCollector)
    c.pcfg = pcfg
    c._iter_seq = 0
    c._weights_version = 1
    c._drain_timeout_s = timeout
    c._queue = q
    return c


def test_ppo_async_collect_compute_gae_per_episode():
    """drain 1 episode → 算 GAE → transitions 带 advantage + return。"""
    import queue as _q

    from training.core.protocols import Transition

    pcfg = PPOParadigmConfig.from_dict({'gamma': 0.99, 'gae_lambda': 0.95, 'rollout': {'n_games_per_iter': 1}})
    trans = [
        Transition(
            obs=None, action=0, legal_mask=None, reward=1.0, done=False, payload={'value': 0.5, 'log_prob': 0.0}
        ),
        Transition(
            obs=None, action=1, legal_mask=None, reward=-1.0, done=False, payload={'value': 0.0, 'log_prob': 0.0}
        ),
    ]
    drained = []

    class _MockQ:
        def get(self, timeout):
            if drained:
                raise _q.Empty()
            drained.append(1)
            return trans

    c = _make_unspawned(pcfg, _MockQ())
    out = c.collect(n_units=1, provider=None)
    assert out.n_units == 2 and len(out.transitions) == 2 and out.transitions[1].done is True
    # GAE(γ=0.99, λ=0.95):t=1 done → A=-1, R=-1;t=0 → A=-0.4405, R=0.0595。
    assert out.transitions[1].payload['advantage'] == pytest.approx(-1.0, abs=1e-5)
    assert out.transitions[1].payload['return'] == pytest.approx(-1.0, abs=1e-5)
    assert out.transitions[0].payload['advantage'] == pytest.approx(-0.4405, abs=1e-4)
    assert out.transitions[0].payload['return'] == pytest.approx(0.0595, abs=1e-4)
    assert out.runtime_metrics['n_episodes_drained'] == 1


def test_ppo_async_collect_timeout_returns_empty():
    """Queue 永远空 → collect timeout 后返回 empty,不 hang。"""
    import queue as _q
    import time

    pcfg = PPOParadigmConfig.from_dict({'rollout': {'n_games_per_iter': 1}})

    class _EmptyQ:
        def get(self, timeout):
            raise _q.Empty()

    c = _make_unspawned(pcfg, _EmptyQ(), timeout=0.5)
    t0 = time.time()
    out = c.collect(n_units=1, provider=None)
    assert (time.time() - t0) < 2.0 and out.n_units == 0 and out.runtime_metrics['n_episodes_drained'] == 0


def test_ppo_async_n_actors_validation_and_paradigm_dispatch():
    """num_actors < 1 → ValueError;paradigm.make_collector(mode='async') →
    PPOAsyncCollector 类型(stub __init__ 跳过 mp)。Unknown mode → ValueError。"""
    from training.core.network import AgentConfig
    from training.paradigms.ppo._async import PPOAsyncCollector
    from training.paradigms.ppo.paradigm import PPOParadigm

    pcfg = PPOParadigmConfig.from_dict({})
    agent_cfg = AgentConfig(
        n_counter_slots=128,
        n_hooks=4,
        max_ops_per_hook=8,
        max_actions=4,
        d_model=8,
        n_cross_layers=1,
        dropout=0.0,
    )
    net = PPONetwork(agent_cfg)

    class _BadCfg:
        class pipeline:
            num_actors = 0

        class meta:
            seed = 0

    with pytest.raises(ValueError, match='num_actors must be ≥ 1'):
        PPOAsyncCollector(_BadCfg(), pcfg, net)

    # paradigm dispatch — stub __init__ 跳过 mp。
    captured = {}

    def _stub(self, cfg, paradigm_cfg, network, env_factory=None):
        captured['ef'] = env_factory

    p = PPOParadigm()
    p._pcfg = pcfg
    orig = PPOAsyncCollector.__init__
    PPOAsyncCollector.__init__ = _stub
    try:
        col = p.make_collector(_AsyncCfg(), env_factory='ef', network=net, opp_pool=None)
        assert isinstance(col, PPOAsyncCollector) and captured['ef'] == 'ef'
    finally:
        PPOAsyncCollector.__init__ = orig

    class _BogusCfg:
        class pipeline:
            mode = 'bogus'

        class meta:
            seed = 0

    with pytest.raises(ValueError, match='unknown pipeline.mode'):
        p.make_collector(_BogusCfg(), env_factory=None, network=None, opp_pool=None)
