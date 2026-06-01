"""Unit tests for training/paradigms/az/mp_factories.py (I31 #88 AZ T1, B').

Mock-light: a fake InferenceClient (records its evaluator calls) + real
AZParadigmConfig reconstruction (per CLAUDE.md: correctness tests use real
interfaces where cheap). The full selfplay game itself is monkeypatched in
the runner test — a real game needs GicgEnv + DSL + an InferenceServer; that
lives in the T7 smoke_full e2e, not this fast unit suite.

Covers AZ tasks.md T1:
  1. build_az_provider raises ValueError when inference_client is None
  2. build_az_provider with a fake client → _AZRemoteProvider holding
     card_pool_spec / mcts_config / n_counter_slots / max_actions; game_start /
     eval_state / game_end delegate to the client
  3. AZSelfPlayRunner.run with a fake env_factory + monkeypatched play_self_game
     → _AZRunnerOutput carrying the SelfPlayResult; env built with the spec seed
     and closed in finally
  4. az_spec_sampler → opponent_id='self', monotonic per-actor seeds
  5. build_az_policy stub.act raises; build_az_opp_registry empty
  6. _AZRunnerOutput pickles round-trip
"""

from __future__ import annotations

import pickle

import numpy as np
import pytest

import training.paradigms.az.mp_factories as mpf
from training.core.protocols import EpisodeSpec
from training.core.scenario import ScenarioConfig
from training.paradigms.az.config import AZParadigmConfig
from training.paradigms.az.mp_factories import (
    _SPEC_COUNTERS,
    _AZRemoteProvider,
    _AZRunnerOutput,
    _AZSelfPlayPolicy,
    az_spec_sampler,
    build_az_opp_registry,
    build_az_policy,
    build_az_provider,
    build_az_selfplay_runner,
)
from training.paradigms.az.selfplay import SelfPlayResult

# Tiny shapes — keep AZParadigmConfig reconstruction cheap.
_N_COUNTER_SLOTS = 64
_MAX_ACTIONS = 8


class _Meta:
    seed = 123
    device = 'cpu'


# Real ScenarioConfig (same shape as AZ smoke_config) — provider construction
# exercises the real make_pool_spec / resolve_pool_refs path against DSL data/.
_SCENARIO = ScenarioConfig(
    team_0=['赤蝶'],
    team_1=['赤蝶'],
    card_pool=None,
    data_dir='data',
    deck_padding={'card': '碌碌无为', 'target_size': 15},
    pool=['v_legacy', 'test_basic'],
)


class _Cfg:
    """Minimal cfg stub. ``paradigm`` is a dict (mp-spawn shape) that
    AZParadigmConfig.from_dict accepts; agent overrides shrink the obs shape
    to the tiny test values. ``scenario`` is a real ScenarioConfig so the
    provider's card_pool_spec derivation hits the real resolver."""

    meta = _Meta()
    scenario = _SCENARIO
    paradigm = {
        'version': '1.0.0',
        'paradigm': 'az',
        'max_game_steps': 222,
        'agent': {
            'n_counter_slots': _N_COUNTER_SLOTS,
            'n_hooks': 8,
            'max_ops_per_hook': 4,
            'max_actions': _MAX_ACTIONS,
            'd_model': 8,
            'n_cross_layers': 1,
            'dropout': 0.0,
        },
        'mcts': {'n_rollouts': 4, 'c_puct': 1.4},
    }


class _FakeClient:
    """Records evaluator calls so delegation can be asserted; returns sentinel
    payloads matching the InferenceClient evaluator protocol shapes."""

    def __init__(self, weight_version: int = 7):
        self.current_weight_version = weight_version
        self.calls: list = []
        self.closed = False

    def game_start(self, static_obs):
        self.calls.append(('game_start', static_obs))
        return {'game_static': 'SENTINEL'}

    def eval_state(self, dyn, refs, payments):
        self.calls.append(('eval_state', dyn, refs, payments))
        return (np.zeros((_MAX_ACTIONS,), dtype=np.float32), 0.25)

    def game_end(self):
        self.calls.append(('game_end',))

    def close(self):
        self.closed = True


def test_build_az_provider_raises_on_none_client():
    """Strict contract: missing inference_client → ValueError (no silent
    LocalNetworkProvider fallback in mp mode)."""
    with pytest.raises(ValueError, match='inference_client kwarg required'):
        build_az_provider(_Cfg(), actor_id=0, inference_client=None)
    # Default (no kwarg) also raises.
    with pytest.raises(ValueError, match='inference_client kwarg required'):
        build_az_provider(_Cfg(), actor_id=0)


def test_build_az_provider_holds_cfg_state():
    """Provider derives + holds the selfplay config the runner reads off it."""
    client = _FakeClient()
    provider = build_az_provider(_Cfg(), actor_id=3, inference_client=client)
    assert isinstance(provider, _AZRemoteProvider)

    pcfg = AZParadigmConfig.from_dict(_Cfg.paradigm)
    assert provider.n_counter_slots == pcfg.agent.n_counter_slots == _N_COUNTER_SLOTS
    assert provider.max_actions == pcfg.agent.max_actions == _MAX_ACTIONS
    assert provider.max_game_steps == 222
    assert provider.card_pool_spec is not None
    assert provider.mcts_config is not None
    assert provider.mcts_config.n_rollouts == 4
    # rng deterministic by (seed, label, actor_id) — independent of any other actor.
    import random

    expected = random.Random(mpf.derive_seed(_Meta.seed, 'az_selfplay', 3)).random()
    assert provider.rng.random() == expected


def test_provider_evaluator_delegates_to_client():
    """game_start / eval_state / game_end delegate verbatim to the client."""
    client = _FakeClient(weight_version=11)
    provider = build_az_provider(_Cfg(), actor_id=0, inference_client=client)

    static = np.zeros((4,), dtype=np.float32)
    gs = provider.game_start(static)
    assert gs == {'game_static': 'SENTINEL'}

    dyn = np.zeros((3,), dtype=np.float32)
    refs = np.zeros((2,), dtype=np.int64)
    pay = np.zeros((2,), dtype=np.float32)
    prior, value = provider.eval_state(dyn, refs, pay)
    assert prior.shape == (_MAX_ACTIONS,) and value == 0.25

    provider.game_end()

    kinds = [c[0] for c in client.calls]
    assert kinds == ['game_start', 'eval_state', 'game_end']
    # static obs passed through unchanged (same object).
    assert client.calls[0][1] is static
    assert client.calls[1][1] is dyn and client.calls[1][2] is refs and client.calls[1][3] is pay


def test_provider_version_and_close():
    """current_version reads client weight version; update_weights is a no-op
    version-read (server owns weights); close delegates to the client."""
    client = _FakeClient(weight_version=9)
    provider = build_az_provider(_Cfg(), actor_id=0, inference_client=client)
    assert provider.current_version() == 9
    assert provider.update_weights() == 9

    # A cold client (version < 0) reports 0, not a negative.
    cold = _FakeClient(weight_version=-1)
    p2 = build_az_provider(_Cfg(), actor_id=0, inference_client=cold)
    assert p2.current_version() == 0

    provider.close()
    assert client.closed is True


class _FakeEnv:
    def __init__(self, seed):
        self.seed = seed
        self.closed = False

    def close(self):
        self.closed = True


class _FakeRunnerProvider:
    """Holds the runner-read config attrs (no real client needed for the runner
    wiring test — play_self_game is monkeypatched)."""

    def __init__(self):
        import random

        self.card_pool_spec = object()
        self.mcts_config = object()
        self.n_counter_slots = _N_COUNTER_SLOTS
        self.max_actions = _MAX_ACTIONS
        self.max_game_steps = 222
        self.rng = random.Random(0)


def test_az_selfplay_runner_runs_one_game(monkeypatch):
    """AZSelfPlayRunner.run builds env from spec seed, calls play_self_game with
    the provider as evaluator + provider-held config, closes env in finally, and
    wraps the SelfPlayResult in _AZRunnerOutput (transitions == [])."""
    captured = {}

    def _env_factory(scenario_seed):
        env = _FakeEnv(scenario_seed)
        captured['env'] = env
        return env

    fake_result = SelfPlayResult(
        game_static={'k': 1},
        steps=[{'pi_target': np.zeros(3, dtype=np.float32)}],
        winner=0,
        n_steps=1,
        discovery_count=0,
    )

    def _fake_play(evaluator, env, card_pool_spec, rng, mcts_config, *, max_game_steps, n_counter_slots, max_actions):
        captured['call'] = dict(
            evaluator=evaluator,
            env=env,
            card_pool_spec=card_pool_spec,
            rng=rng,
            mcts_config=mcts_config,
            max_game_steps=max_game_steps,
            n_counter_slots=n_counter_slots,
            max_actions=max_actions,
        )
        return fake_result

    monkeypatch.setattr(mpf, 'play_self_game', _fake_play)

    runner = build_az_selfplay_runner(_env_factory, opp_registry=object())
    provider = _FakeRunnerProvider()
    spec = EpisodeSpec(scenario_seed=999, opponent_id='self')
    out = runner.run(spec, policy=None, provider=provider)

    assert isinstance(out, _AZRunnerOutput)
    assert out.transitions == []
    assert out.selfplay_result is fake_result

    call = captured['call']
    assert call['evaluator'] is provider  # provider IS the evaluator
    assert call['env'] is captured['env'] and captured['env'].seed == 999
    assert call['card_pool_spec'] is provider.card_pool_spec
    assert call['mcts_config'] is provider.mcts_config
    assert call['rng'] is provider.rng
    assert call['max_game_steps'] == 222
    assert call['n_counter_slots'] == _N_COUNTER_SLOTS
    assert call['max_actions'] == _MAX_ACTIONS
    # env closed in finally even on the happy path.
    assert captured['env'].closed is True


def test_az_selfplay_runner_closes_env_on_error(monkeypatch):
    """env.close() runs even when play_self_game raises (finally)."""
    captured = {}

    def _env_factory(scenario_seed):
        env = _FakeEnv(scenario_seed)
        captured['env'] = env
        return env

    def _boom(*args, **kwargs):
        raise RuntimeError('selfplay boom')

    monkeypatch.setattr(mpf, 'play_self_game', _boom)

    runner = build_az_selfplay_runner(_env_factory, opp_registry=None)
    with pytest.raises(RuntimeError, match='selfplay boom'):
        runner.run(EpisodeSpec(scenario_seed=7, opponent_id='self'), policy=None, provider=_FakeRunnerProvider())
    assert captured['env'].closed is True


def test_az_spec_sampler_self_and_monotonic():
    """opponent_id='self'; repeated calls → distinct deterministic seeds;
    independent per-actor counter."""
    _SPEC_COUNTERS.clear()
    a0 = [az_spec_sampler(_Cfg(), actor_id=0) for _ in range(4)]
    assert all(s.opponent_id == 'self' for s in a0)
    seeds = [s.scenario_seed for s in a0]
    assert len(set(seeds)) == 4, f'expected 4 distinct seeds, got {seeds}'

    # Reproducible: same (seed, actor, seq) reproduces the same seeds.
    _SPEC_COUNTERS.clear()
    a0_again = [az_spec_sampler(_Cfg(), actor_id=0).scenario_seed for _ in range(4)]
    assert seeds == a0_again

    # Distinct actor → independent counter (starts at seq=0), different seed.
    _SPEC_COUNTERS.clear()
    s_a0 = az_spec_sampler(_Cfg(), actor_id=0)
    s_a5 = az_spec_sampler(_Cfg(), actor_id=5)
    assert s_a0.scenario_seed != s_a5.scenario_seed


def test_build_az_policy_stub_act_raises():
    """Stub policy exists only for actor_main validation; act raises loud."""
    policy = build_az_policy(_Cfg(), actor_id=0)
    assert isinstance(policy, _AZSelfPlayPolicy)
    policy.reset()  # no-op, must not raise
    with pytest.raises(RuntimeError, match='_AZSelfPlayPolicy.act called'):
        policy.act(None, None, None)


def test_build_az_opp_registry_empty():
    """Empty registry (selfplay never looks up an opponent)."""
    reg = build_az_opp_registry(_Cfg())
    assert reg is not None
    # OpponentRegistry has no registered opponents; the 'self' sentinel is
    # never resolved by the runner.
    from training.core.eval.baselines import OpponentRegistry

    assert isinstance(reg, OpponentRegistry)


def test_az_runner_output_pickles():
    """_AZRunnerOutput + its SelfPlayResult (dicts/lists/ints/numpy) round-trip
    through pickle for the SHMRing / IPCQueue transport."""
    result = SelfPlayResult(
        game_static={'static': np.zeros((4,), dtype=np.int32)},
        steps=[
            {'pi_target': np.ones(3, dtype=np.float32), 'z_target': 1.0, 'is_discovery': False},
            {'pi_target': np.zeros(3, dtype=np.float32), 'z_target': -1.0, 'is_discovery': True},
        ],
        winner=1,
        n_steps=2,
        discovery_count=1,
        mcts_profile={'n_eval': 12},
    )
    out = _AZRunnerOutput(transitions=[], selfplay_result=result)
    blob = pickle.dumps(out, protocol=pickle.HIGHEST_PROTOCOL)
    rt = pickle.loads(blob)
    assert isinstance(rt, _AZRunnerOutput)
    assert rt.transitions == []
    assert rt.selfplay_result.winner == 1 and rt.selfplay_result.n_steps == 2
    assert rt.selfplay_result.discovery_count == 1
    np.testing.assert_array_equal(rt.selfplay_result.steps[0]['pi_target'], np.ones(3, dtype=np.float32))
