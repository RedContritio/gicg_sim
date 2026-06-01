"""Unit tests for training/paradigms/cfr/mp_factories.py (I31 #88 CFR T3).

Mock-light: real tiny AdvantageNet pair + real owner-side WeightsSHM + real
CFRParadigmConfig reconstruction (per CLAUDE.md: correctness tests use real
interfaces). The traverser tree-walk itself is monkeypatched in the runner
test (a real traversal needs GicgEnv + DSL — that lives in the smoke_full
e2e test, not this fast unit suite).

Covers CFR tasks.md T7:
  1. build_provider constructs a _CFRActorProvider with traverser + 2 loaded nets
  2. CFRTraversalRunner.run drives one traversal → non-empty cfr_batch, [] transitions
  3. cfr_spec_sampler EpisodeSpec field-reuse encode round-trips (D1.B)
  4. cfr_spec_sampler per-actor seq monotonic (distinct seeds / alternating side)
"""

from __future__ import annotations

import pickle

import numpy as np
import pytest
import torch

from training.core.actor.weights_shm import WeightsSHM
from training.paradigms.cfr._collect_helpers import CollectorBuffer
from training.paradigms.cfr.advantage_net import AdvantageNet
from training.paradigms.cfr.mp_factories import (
    _SPEC_COUNTERS,
    _CFRActorProvider,
    _CFRRunnerOutput,
    build_cfr_traversal_runner,
    build_provider,
    cfr_spec_sampler,
)
from training.paradigms.cfr.strategy_net import CFRNetConfig

# Tiny shapes — fast net construction. n_counter_slots/n_hooks must be large
# enough for the encoder embeddings (CounterEncoder max_slots=2000 internally).
_NET_CFG = CFRNetConfig(
    n_counter_slots=64,
    n_hooks=8,
    max_ops_per_hook=4,
    max_actions=8,
    d_model=8,
    n_cross_layers=1,
    dropout=0.0,
)


class _Meta:
    seed = 123
    device = 'cpu'


class _Scenario:
    team_0 = ['赤蝶']
    team_1 = ['墨客']
    card_pool = None
    data_dir = 'data'
    max_rounds = 3
    deck_padding = None
    pool = ['v_legacy', 'test_basic']
    fix_dice = None


class _Cfg:
    """Minimal cfg stub. ``paradigm`` is a dict (mp-spawn shape) that
    CFRParadigmConfig.from_dict accepts; agent overrides shrink the net to
    the tiny test shape so build_provider's reconstructed CFRNetConfig matches
    the blueprint nets' shapes."""

    meta = _Meta()
    scenario = _Scenario()
    paradigm = {
        'version': '1.0.0',
        'paradigm': 'cfr',
        'agent': {
            'n_counter_slots': _NET_CFG.n_counter_slots,
            'n_hooks': _NET_CFG.n_hooks,
            'max_ops_per_hook': _NET_CFG.max_ops_per_hook,
            'max_actions': _NET_CFG.max_actions,
            'd_model': _NET_CFG.d_model,
            'n_cross_layers': _NET_CFG.n_cross_layers,
            'dropout': _NET_CFG.dropout,
        },
        'traversal': {'sampling_mode': 'os', 'epsilon': 0.1, 'max_game_steps': 400},
    }


def _make_two_nets() -> list:
    torch.manual_seed(0)
    n0 = AdvantageNet(_NET_CFG)
    torch.manual_seed(1)
    n1 = AdvantageNet(_NET_CFG)
    return [n0.cpu(), n1.cpu()]


def _owner_shm_with_two_slots(nets) -> WeightsSHM:
    shm = WeightsSHM(max_state_dict_bytes=8 * 1024 * 1024, owner=True)
    for p in range(2):
        sd = {k: v.detach().cpu() for k, v in nets[p].state_dict().items()}
        shm.write(f'cfr_adv_p{p}', sd, version=1)
    return shm


def _static() -> dict:
    return {
        'hook_ir': np.zeros((_NET_CFG.n_hooks, _NET_CFG.max_ops_per_hook, 5), dtype=np.int32),
        'hook_mask': np.ones((_NET_CFG.n_hooks,), dtype=bool),
        'counter_sids': np.zeros((_NET_CFG.n_counter_slots,), dtype=np.int64),
        'active_slot_mask': np.ones((_NET_CFG.n_counter_slots,), dtype=bool),
        'char_skill_refs': np.full((2, 4), -1, dtype=np.int64),
    }


def _dynamic() -> dict:
    return {
        'counter_values': np.zeros((_NET_CFG.n_counter_slots,), dtype=np.float32),
        'meta': np.zeros((8,), dtype=np.float32),
        'card_buckets': np.zeros((4,), dtype=np.float32),
        'enemy_sizes': np.zeros((2,), dtype=np.float32),
        'action_refs': np.zeros((_NET_CFG.max_actions, 3), dtype=np.int64),
        'action_payments': np.zeros((_NET_CFG.max_actions, 8), dtype=np.float32),
        'legal_mask': np.ones((_NET_CFG.max_actions,), dtype=bool),
        'structural_values': np.zeros((4,), dtype=np.float32),
    }


def test_build_provider_constructs_traverser(tmp_path):
    """build_provider: WeightsSHM.attach (2 slots) + 2-net blueprint →
    _CFRActorProvider with a non-None traverser + both nets loaded."""
    nets = _make_two_nets()
    blueprint = tmp_path / 'net.pkl'
    with open(blueprint, 'wb') as f:
        pickle.dump(nets, f, protocol=pickle.HIGHEST_PROTOCOL)

    shm = _owner_shm_with_two_slots(nets)
    try:
        info = shm.serialize_for_worker(['cfr_adv_p0', 'cfr_adv_p1'])
        provider = build_provider(
            _Cfg(),
            actor_id=0,
            weights_shm_info=info,
            network_blueprint_path=str(blueprint),
        )
        assert isinstance(provider, _CFRActorProvider)
        assert provider.traverser is not None
        assert len(provider.traverser.advantage_nets) == 2
        assert len(provider.adv_cols) == 2
        # Initial versions read from SHM (both written at version=1).
        assert provider.current_version() == 1
        provider.close()
    finally:
        shm.close()


def test_build_provider_raises_on_cold_slot(tmp_path):
    """Strict contract: a cold SHM slot → RuntimeError (parent must publish
    both before spawn)."""
    nets = _make_two_nets()
    blueprint = tmp_path / 'net.pkl'
    with open(blueprint, 'wb') as f:
        pickle.dump(nets, f, protocol=pickle.HIGHEST_PROTOCOL)

    shm = WeightsSHM(max_state_dict_bytes=8 * 1024 * 1024, owner=True)
    # Only publish p0 — p1 stays cold.
    sd0 = {k: v.detach().cpu() for k, v in nets[0].state_dict().items()}
    shm.write('cfr_adv_p0', sd0, version=1)
    try:
        info = shm.serialize_for_worker(['cfr_adv_p0'])
        with pytest.raises(RuntimeError, match='cfr_adv_p1 cold'):
            build_provider(_Cfg(), actor_id=0, weights_shm_info=info, network_blueprint_path=str(blueprint))
    finally:
        shm.close()


def test_build_provider_raises_on_bad_blueprint(tmp_path):
    """Blueprint must be exactly 2 nets — 1 net → RuntimeError."""
    nets = _make_two_nets()
    blueprint = tmp_path / 'net.pkl'
    with open(blueprint, 'wb') as f:
        pickle.dump([nets[0]], f, protocol=pickle.HIGHEST_PROTOCOL)  # only 1 net

    shm = _owner_shm_with_two_slots(nets)
    try:
        info = shm.serialize_for_worker(['cfr_adv_p0', 'cfr_adv_p1'])
        with pytest.raises(RuntimeError, match='must be 2 AdvantageNet'):
            build_provider(_Cfg(), actor_id=0, weights_shm_info=info, network_blueprint_path=str(blueprint))
    finally:
        shm.close()


class _FakeEnv:
    def __init__(self, seed):
        self.seed = seed
        self.closed = False

    def close(self):
        self.closed = True


class _FakeTraverser:
    """Pushes known samples into the provider's cols (mimics one traversal of
    traverser_player=0)."""

    def __init__(self, adv_cols, strat_col, val_col):
        self._adv_cols = adv_cols
        self._strat_col = strat_col
        self._val_col = val_col

    def traverse(self, env, traverser_player, iteration):
        gid_a = self._adv_cols[traverser_player].register_game(_static())
        self._adv_cols[traverser_player].add_sample(
            gid_a, _dynamic(), np.zeros((_NET_CFG.max_actions,), dtype=np.float32), iteration
        )
        gid_s = self._strat_col.register_game(_static())
        self._strat_col.add_sample(gid_s, _dynamic(), np.zeros((_NET_CFG.max_actions,), dtype=np.float32), iteration)
        gid_v = self._val_col.register_game(_static())
        self._val_col.add_sample(gid_v, _dynamic(), 0.5, iteration)


class _FakeProvider:
    def __init__(self):
        self.adv_cols = [CollectorBuffer(), CollectorBuffer()]
        self.strat_col = CollectorBuffer()
        self.val_col = CollectorBuffer()
        self.traverser = _FakeTraverser(self.adv_cols, self.strat_col, self.val_col)


def test_cfr_traversal_runner_runs_one_traversal():
    """CFRTraversalRunner.run drives traverser.traverse + drains →
    _CFRRunnerOutput with non-empty cfr_batch and transitions == []."""
    captured = {}

    def _env_factory(scenario_seed):
        env = _FakeEnv(scenario_seed)
        captured['env'] = env
        return env

    runner = build_cfr_traversal_runner(_env_factory, opp_registry=object())
    provider = _FakeProvider()

    # Encode a spec the D1.B way: traverser_player=0 (starting_player),
    # iteration=3 (epsilon).
    from training.core.protocols import EpisodeSpec

    spec = EpisodeSpec(scenario_seed=999, opponent_id='cfr_traverser', starting_player=0, epsilon=3.0)
    out = runner.run(spec, policy=None, provider=provider)

    assert isinstance(out, _CFRRunnerOutput)
    assert out.transitions == []
    n_a0, n_a1, n_s, n_v = out.cfr_batch.n_samples()
    assert (n_a0, n_a1, n_s, n_v) == (1, 0, 1, 1)
    # env was built with the decoded scenario_seed and closed in finally.
    assert captured['env'].seed == 999 and captured['env'].closed is True


def test_cfr_spec_encode_roundtrip():
    """D1.B field-reuse encode → decode round-trips iteration + traverser_player;
    opponent_id is the sentinel."""
    _SPEC_COUNTERS.clear()
    spec = cfr_spec_sampler(_Cfg(), actor_id=0)  # seq=0
    assert spec.opponent_id == 'cfr_traverser'
    # decode (mirrors CFRTraversalRunner.run)
    assert int(spec.epsilon) == 0  # iteration = seq = 0
    assert int(spec.starting_player) == 0  # seq % 2

    spec2 = cfr_spec_sampler(_Cfg(), actor_id=0)  # seq=1
    assert int(spec2.epsilon) == 1
    assert int(spec2.starting_player) == 1  # alternated


def test_cfr_spec_sampler_monotonic_seq():
    """Repeated calls for one actor advance seq → distinct scenario_seeds +
    alternating starting_player; independent counter per actor."""
    _SPEC_COUNTERS.clear()
    a0 = [cfr_spec_sampler(_Cfg(), actor_id=0) for _ in range(4)]
    seeds = [s.scenario_seed for s in a0]
    assert len(set(seeds)) == 4, f'expected 4 distinct seeds, got {seeds}'
    assert [s.starting_player for s in a0] == [0, 1, 0, 1]
    assert [int(s.epsilon) for s in a0] == [0, 1, 2, 3]

    # Distinct actor → independent counter (starts at seq=0).
    s_other = cfr_spec_sampler(_Cfg(), actor_id=5)
    assert int(s_other.epsilon) == 0 and int(s_other.starting_player) == 0
    # Different actor_id → different derived seed than actor 0's seq=0.
    assert s_other.scenario_seed != a0[0].scenario_seed


def _cfg_with_alternation(mode: str) -> _Cfg:
    cfg = _Cfg()
    cfg.paradigm = dict(_Cfg.paradigm, traversal=dict(_Cfg.paradigm['traversal'], traverser_alternation=mode))
    return cfg


def test_cfr_spec_sampler_alternate_default_and_explicit():
    """Missing field defaults to 'alternate' (matches cfg default); explicit
    'alternate' is identical — no silent behavioural difference."""
    _SPEC_COUNTERS.clear()
    default = [cfr_spec_sampler(_Cfg(), actor_id=0).starting_player for _ in range(4)]
    _SPEC_COUNTERS.clear()
    explicit = [cfr_spec_sampler(_cfg_with_alternation('alternate'), actor_id=0).starting_player for _ in range(4)]
    assert default == [0, 1, 0, 1] == explicit


def test_cfr_spec_sampler_honors_random_alternation():
    """'random' traverser_alternation is honored (NOT silently downgraded to
    alternate): both sides sampled, sequence differs from pure alternation, and
    it is deterministic by (seed, actor, seq)."""
    _SPEC_COUNTERS.clear()
    cfg = _cfg_with_alternation('random')
    players = [cfr_spec_sampler(cfg, actor_id=0).starting_player for _ in range(40)]
    assert set(players) == {0, 1}, 'random mode must sample both traverser players'
    assert players != [i % 2 for i in range(40)], 'random must not equal pure alternation'
    # Reproducible: same seed/actor/seq sequence reproduces the same picks.
    _SPEC_COUNTERS.clear()
    players2 = [cfr_spec_sampler(_cfg_with_alternation('random'), actor_id=0).starting_player for _ in range(40)]
    assert players == players2


def test_cfr_spec_sampler_unknown_alternation_raises():
    """Unknown traverser_alternation fails loud — no silent fallback (mirrors the
    serial collector's strict contract)."""
    _SPEC_COUNTERS.clear()
    with pytest.raises(ValueError, match='traverser_alternation'):
        cfr_spec_sampler(_cfg_with_alternation('diagonal'), actor_id=0)
