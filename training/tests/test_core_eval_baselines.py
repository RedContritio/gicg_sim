"""OpponentRegistry + eval helpers tests."""

from __future__ import annotations

import pytest

from training.core.eval.baselines import (
    OpponentRegistry,
    register_default_opponents,
    register_historical_baseline,
)
from training.core.eval.job import EvalResult
from training.core.eval.matchup import aggregate_results
from training.core.eval.scenario import eval_seed_pool
from training.core.eval.statistics import swap_sides_wp, wilson_ci, wp_ci95
from training.core.opponent.mix import WeightedMix
from training.core.opponent.pool import OpponentPool


# ---------- OpponentRegistry ---------- #


def test_register_and_resolve():
    reg = OpponentRegistry()
    reg.register('null', lambda seed, params: None)
    assert reg.get('null', seed=0) is None


def test_unknown_opponent_raises():
    reg = OpponentRegistry()
    with pytest.raises(ValueError, match='unknown opponent'):
        reg.get('foo', seed=0)


def test_collision_raises():
    reg = OpponentRegistry()
    reg.register('x', lambda s, p: None)
    with pytest.raises(ValueError, match='collision'):
        reg.register('x', lambda s, p: None)


def test_register_default_opponents_smoke():
    reg = OpponentRegistry()
    register_default_opponents(reg)
    names = reg.names()
    assert 'random' in names
    assert 'F1-D2' in names
    assert 'mcts_pure_200' in names


def test_register_default_includes_full_mcts_pure_ladder():
    reg = OpponentRegistry()
    register_default_opponents(reg)
    names = reg.names()
    for n in (50, 100, 200, 400):
        assert f'mcts_pure_{n}' in names, f'mcts_pure_{n} missing from defaults'


def test_mcts_pure_resolves_to_player_with_n_rollouts():
    """mcts_pure_<N> SHALL return an MCTSPlayer wired with n_rollouts=N.

    Verifies the registry factory is wired correctly without running
    any rollouts (which would require a GicgEnv)."""
    reg = OpponentRegistry()
    register_default_opponents(reg)
    player = reg.get('mcts_pure_200', seed=7)
    assert player.n_rollouts == 200
    # Distinct seeds SHALL build distinct rng states (sanity — uses seed param).
    p2 = reg.get('mcts_pure_200', seed=8)
    assert player is not p2


# ---------- Historical baseline ---------- #


def test_register_historical_baseline_name_convention():
    """register_historical_baseline SHALL enforce 'historical_' prefix."""
    reg = OpponentRegistry()
    with pytest.raises(ValueError, match="SHALL start with 'historical_'"):
        register_historical_baseline(reg, 'bad_name', '/tmp/x.pt', 'az')


def test_register_historical_baseline_collision_raises():
    reg = OpponentRegistry()
    register_historical_baseline(reg, 'historical_a', '/tmp/x.pt', 'az')
    with pytest.raises(ValueError, match='collision'):
        register_historical_baseline(reg, 'historical_a', '/tmp/y.pt', 'az')


def test_register_historical_baseline_lazy_load_no_file_check():
    """Registration SHALL NOT touch the filesystem — load is lazy on .get().

    Nonexistent ckpt path must register cleanly; failure only surfaces
    on first .get(name) (which triggers torch.load)."""
    reg = OpponentRegistry()
    register_historical_baseline(reg, 'historical_nope', '/nonexistent/ckpt.pt', 'az')
    assert 'historical_nope' in reg.names()


def test_register_historical_baseline_unknown_paradigm_fails_on_get():
    """Unknown paradigm SHALL raise at .get() time via core.matchup.loaders.LOADERS.

    Registration itself is paradigm-string-opaque (lazy import)."""
    reg = OpponentRegistry()
    register_historical_baseline(reg, 'historical_bogus', '/tmp/x.pt', 'nonexistent_paradigm')
    with pytest.raises(ValueError, match='unknown player type'):
        reg.get('historical_bogus', seed=0)


def test_register_historical_baseline_loads_az_ckpt(tmp_path):
    """End-to-end: AZ ckpt round-trip via OpponentRegistry historical entry.

    Builds an AZ agent in smoke_config, saves to tmp, registers, resolves
    — verifies the player object is callable (has select_action)."""
    import os

    from training.paradigms.az.config import smoke_config
    from training.paradigms.az.network import Agent

    data_dir = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
    cfg = smoke_config(data_dir=data_dir)
    agent = Agent(cfg.agent)
    ckpt_path = tmp_path / 'ckpt_historical.pt'
    agent.save(str(ckpt_path))

    reg = OpponentRegistry()
    register_historical_baseline(reg, 'historical_smoke', str(ckpt_path), 'az')
    player = reg.get('historical_smoke', seed=0)
    assert hasattr(player, 'select_action'), 'historical player SHALL implement select_action(env)'


# ---------- WeightedMix ---------- #


def test_weighted_mix_sample_in_names():
    mix = WeightedMix(['a', 'b'], [1, 1], seed=0)
    s = mix.sample()
    assert s in ('a', 'b')


def test_weighted_mix_zero_weights_raises():
    with pytest.raises(ValueError, match='sum to 0'):
        WeightedMix(['a', 'b'], [0, 0])


def test_weighted_mix_len_mismatch_raises():
    with pytest.raises(ValueError, match='!='):
        WeightedMix(['a'], [1, 1])


def test_weighted_mix_negative_raises():
    with pytest.raises(ValueError, match='negative weight'):
        WeightedMix(['a', 'b'], [-1, 1])


# ---------- OpponentPool ---------- #


def test_opponent_pool_random_only():
    reg = OpponentRegistry()
    reg.register('random', lambda seed, params: 'random_player')
    pool = OpponentPool(reg, weights={'random': 1.0})
    assert pool.sample() == 'random_player'


def test_opponent_pool_unknown_in_weights_raises():
    reg = OpponentRegistry()
    reg.register('random', lambda seed, params: None)
    with pytest.raises(ValueError, match='unknown opponent'):
        OpponentPool(reg, weights={'random': 1.0, 'foo': 1.0})


def test_opponent_pool_historical_cold_falls_back_to_random():
    reg = OpponentRegistry()
    reg.register('random', lambda seed, params: 'random_player')
    pool = OpponentPool(reg, weights={'historical': 1.0})
    assert pool.sample() == 'random_player'


def test_opponent_pool_historical_with_factory():
    reg = OpponentRegistry()
    reg.register('random', lambda seed, params: 'random_player')
    pool = OpponentPool(reg, weights={'historical': 1.0}, historical_factory=lambda sd: f'h:{sd}')
    pool.add_snapshot('ckpt-1')
    out = pool.sample()
    assert out.startswith('h:')


# ---------- Statistics ---------- #


def test_wp_ci95_smoke():
    p, lo, hi = wp_ci95(wins=50, n_games=100)
    assert abs(p - 0.5) < 1e-9
    assert lo < p < hi


def test_wilson_ci_smoke():
    lo, hi = wilson_ci(wins=8, n_games=10)
    assert 0 <= lo <= hi <= 1


def test_swap_sides_wp():
    mean, p0, p1 = swap_sides_wp(wins_p0=3, n_p0=5, wins_p1=2, n_p1=5)
    assert mean == 0.5
    assert p0 == 0.6
    assert p1 == 0.4


def test_wp_ci95_zero_games_raises():
    with pytest.raises(ValueError, match='< 1'):
        wp_ci95(wins=0, n_games=0)


# ---------- aggregate_results + EvalResult ---------- #


def test_aggregate_swap_sides():
    results = [
        EvalResult(job_id='j', game_idx=0, winner=0, our_player=0, length=10),
        EvalResult(job_id='j', game_idx=1, winner=1, our_player=1, length=10),
        EvalResult(job_id='j', game_idx=2, winner=1, our_player=0, length=10),
        EvalResult(job_id='j', game_idx=3, winner=0, our_player=1, length=10),
    ]
    rep = aggregate_results('opp', results)
    # P0 our_player slots [0,2] → wins {True, False} = 1/2; P1 slots [1,3] → wins {True, False} = 1/2
    assert rep.wp_swap_p0 == 0.5
    assert rep.wp_swap_p1 == 0.5
    assert rep.wp_mean == 0.5
    assert rep.n_games == 4


# ---------- eval_seed_pool ---------- #


def test_eval_seed_pool_deterministic():
    a = eval_seed_pool(42, 10)
    b = eval_seed_pool(42, 10)
    assert a == b


def test_eval_seed_pool_size():
    pool = eval_seed_pool(42, 32)
    assert len(pool) == 32
    assert len(set(pool)) > 30  # very few collisions expected with blake2s
