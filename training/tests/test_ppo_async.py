"""Unit tests for PPOAsyncCollector (FU-W3b-PPO 真 mp 接通)。

Split from test_ppo_paradigm.py for line-limit hook compliance。Mock-only
(no GicgEnv / no real spawn)— end-to-end smoke 在 future smoke cfg ship
(PPO frozen tier 不预期 production async run)。
"""

from __future__ import annotations

import pytest

from training.paradigms.ppo.config import PPOParadigmConfig
from training.paradigms.ppo.network import PPONetwork


class _AsyncCfg:
    """Minimal cfg stub(避开 TOML load + GicgEnv 触碰)。"""

    paradigm = {'gamma': 0.95, 'gae_lambda': 0.9}

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
    from training.paradigms.ppo._async import build_policy

    p0, p1 = build_policy(_AsyncCfg(), 0), build_policy(_AsyncCfg(), 1)
    assert p0.gamma == 0.95 and p0.gae_lambda == 0.9 and p0.deterministic is False
    assert p0._np_rng.bit_generator.state != p1._np_rng.bit_generator.state


def test_ppo_async_spec_sampler_monotonic_and_self_to_random():
    """spec_sampler:per-actor 单调 + opp 'self' → 'random'(frozen 不接 self-play)。"""
    import os

    from training.paradigms.ppo._async import _ENV_OPPONENT, _SPEC_COUNTERS, spec_sampler

    _SPEC_COUNTERS.clear()
    s0 = spec_sampler(_AsyncCfg(), actor_id=0)
    s1 = spec_sampler(_AsyncCfg(), actor_id=0)
    s2 = spec_sampler(_AsyncCfg(), actor_id=1)
    assert s0.scenario_seed != s1.scenario_seed != s2.scenario_seed
    assert s0.opponent_id == 'random'  # env var unset → default

    _SPEC_COUNTERS.clear()
    os.environ[_ENV_OPPONENT] = 'self'
    try:
        assert spec_sampler(_AsyncCfg(), 0).opponent_id == 'random'  # 退化
    finally:
        os.environ.pop(_ENV_OPPONENT, None)


def test_ppo_async_provider_wraps_local_and_shm():
    """_PPOActorProvider:forward 委托 + SHM 新 version → load,旧 / cold → skip。"""
    from training.paradigms.ppo._async import _PPOActorProvider

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
