"""AB14 contract tests — actor_main ``episode_runner_factory`` escape hatch.

In-proc (no real spawn): fake env_factory / opp_registry / policy / provider /
spec_sampler + ``should_stop`` flipping after one iteration + a stub queue. We
observe which Runner ``actor_main`` constructs and that it composes orthogonally
with the AB13 provider-handoff hatches.

Mirrors the in-proc actor_main pattern in
``training/tests/test_ppo_async.py::test_ppo_async_provider_kwargs_handoff``.
The CFR-local CFRTraversalRunner + its lifecycle land in a later task; this
file only pins the core dispatch contract that AB14 adds to actor_main.
"""

from __future__ import annotations

import pytest

from training.core.actor.actor_process import actor_main
from training.core.protocols import EpisodeSpec


# ---------- fakes (top-level so dotted-path resolution can reach them) ---------- #


class _FakeRecord:
    """EpisodeRunner.run-shaped output: actor_main pushes ``.transitions``."""

    transitions = ['t0', 't1']


class _FakeRunner:
    """Records construction args + run() calls; returns an episode-shaped record."""

    last_instance = None

    def __init__(self, env_factory, opp_registry):
        self.env_factory = env_factory
        self.opp_registry = opp_registry
        self.run_calls = 0
        type(self).last_instance = self

    def run(self, spec, policy, provider):
        self.run_calls += 1
        return _FakeRecord()


def _fake_runner_factory(env_factory, opp_registry):
    """AB14 factory: ``(env_factory, opp_registry) -> Runner``."""
    return _FakeRunner(env_factory, opp_registry)


def _fake_env_factory(cfg, seed):
    return lambda scenario_seed: object()


def _fake_opp_registry(cfg):
    return {}


def _fake_policy(cfg, actor_id):
    return object()


class _FakeProvider:
    def forward(self, obs, mask):
        return None

    def update_weights(self):
        return 1

    def close(self):
        pass


def _fake_provider(cfg, actor_id, **kw):
    # Accept provider_kwargs so the orthogonality test can pass a handoff dict.
    return _FakeProvider()


def _fake_spec_sampler(cfg, actor_id):
    return EpisodeSpec(scenario_seed=actor_id, opponent_id='whatever')


class _StubQueue:
    """Captures items actor_main pushes; flips should_stop after first push."""

    def __init__(self):
        self.items = []

    def put(self, item):
        self.items.append(item)


class _MetaCfg:
    seed = 11
    paradigm = 'cfr'


class _Cfg:
    meta = _MetaCfg()


class _StopAfter:
    """should_stop() returns False once, then True — exactly one loop body."""

    def __init__(self):
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.calls > 1


# ---------- tests ---------- #


def test_episode_runner_factory_callable_used_over_default():
    """AB14: when ``episode_runner_factory`` is given, actor_main builds the
    runner via the factory (not the default EpisodeRunner), and drives its
    ``run`` — observed via the fake runner's call counter + queue payload."""
    _FakeRunner.last_instance = None
    q = _StubQueue()
    actor_main(
        actor_id=3,
        cfg=_Cfg(),
        build_env_factory=_fake_env_factory,
        build_opp_registry=_fake_opp_registry,
        build_policy=_fake_policy,
        build_provider=_fake_provider,
        spec_sampler=_fake_spec_sampler,
        transition_queue=q,
        should_stop=_StopAfter(),
        episode_runner_factory=_fake_runner_factory,
    )
    runner = _FakeRunner.last_instance
    assert runner is not None, 'factory was never invoked — default EpisodeRunner used'
    assert isinstance(runner, _FakeRunner)
    assert runner.run_calls == 1
    # Pushed .transitions (push_episode_record default False).
    assert q.items == [['t0', 't1']]


def test_episode_runner_factory_path_resolved_via_resolve_builder():
    """AB14 dotted dual: ``episode_runner_factory_path`` is import-resolved
    through ``resolve_builder`` and used identically to the callable form."""
    _FakeRunner.last_instance = None
    q = _StubQueue()
    actor_main(
        actor_id=4,
        cfg=_Cfg(),
        build_env_factory=_fake_env_factory,
        build_opp_registry=_fake_opp_registry,
        build_policy=_fake_policy,
        build_provider=_fake_provider,
        spec_sampler=_fake_spec_sampler,
        transition_queue=q,
        should_stop=_StopAfter(),
        episode_runner_factory_path=('training.core.actor.tests.test_actor_main_runner_factory._fake_runner_factory'),
    )
    runner = _FakeRunner.last_instance
    assert isinstance(runner, _FakeRunner)
    assert runner.run_calls == 1
    assert q.items == [['t0', 't1']]


def test_runner_factory_orthogonal_to_provider_kwargs_no_raise():
    """Orthogonality (AB14 ⟂ AB13): episode_runner_factory + provider_kwargs
    together do NOT raise — they are independent axes. The Axis-1 mutex only
    fires for inference_client + provider_kwargs."""
    _FakeRunner.last_instance = None
    captured: dict = {}

    def _provider_capturing_kwargs(cfg, actor_id, **kw):
        captured.update(kw)
        return _FakeProvider()

    q = _StubQueue()
    actor_main(
        actor_id=5,
        cfg=_Cfg(),
        build_env_factory=_fake_env_factory,
        build_opp_registry=_fake_opp_registry,
        build_policy=_fake_policy,
        build_provider=_provider_capturing_kwargs,
        spec_sampler=_fake_spec_sampler,
        transition_queue=q,
        should_stop=_StopAfter(),
        episode_runner_factory=_fake_runner_factory,
        provider_kwargs={'weights_shm_info': {'fake': 'shm'}, 'network_blueprint_path': '/tmp/bp.pkl'},
    )
    # Both hatches took effect: factory built the runner AND provider_kwargs
    # was spread into build_provider.
    assert isinstance(_FakeRunner.last_instance, _FakeRunner)
    assert captured == {'weights_shm_info': {'fake': 'shm'}, 'network_blueprint_path': '/tmp/bp.pkl'}


def test_inference_client_plus_provider_kwargs_still_mutex():
    """Guard: the AB13 mutex is unchanged by AB14 — inference_client +
    provider_kwargs together still raise, even with a runner factory set."""
    q = _StubQueue()
    with pytest.raises(ValueError, match='mutually exclusive'):
        actor_main(
            actor_id=6,
            cfg=_Cfg(),
            build_env_factory=_fake_env_factory,
            build_opp_registry=_fake_opp_registry,
            build_policy=_fake_policy,
            build_provider=_fake_provider,
            spec_sampler=_fake_spec_sampler,
            transition_queue=q,
            should_stop=_StopAfter(),
            episode_runner_factory=_fake_runner_factory,
            inference_client='fake_client',
            provider_kwargs={'fake': 'kwargs'},
        )
