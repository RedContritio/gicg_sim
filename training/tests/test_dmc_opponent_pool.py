"""Contract tests for DMC opponent pool — weighted sampling +
historical ring + cold-start fallback.

OpponentPool / RandomPlayer / OpponentPoolConfig relocated from
``legacy/{opponent_pool,config}.py`` to
``training/paradigms/dmc/_opponent.py`` in FU-W4-DMC.
"""

from __future__ import annotations

from collections import Counter

import pytest

from training.paradigms.dmc._opponent import OpponentPool, OpponentPoolConfig, RandomPlayer
from training.core.matchup.greedy_player import GreedyPlayer


def _balanced_cfg(**overrides) -> OpponentPoolConfig:
    """Default 30/30/10/30 weights; overrideable per test."""
    base = dict(random=0.30, f1d2=0.30, f1d4=0.10, historical=0.30, ring_size=5)
    base.update(overrides)
    return OpponentPoolConfig(**base)


def test_weights_must_sum_to_one():
    """OpponentPoolConfig.__post_init__ guard against silent miscalibration."""
    with pytest.raises(ValueError, match='weights must sum to 1.0'):
        OpponentPoolConfig(random=0.5, f1d2=0.5, f1d4=0.5, historical=0.0)


def test_weights_allowed_with_zero_historical():
    """60/30/10/0 is a valid no-self-play config."""
    cfg = OpponentPoolConfig(random=0.60, f1d2=0.30, f1d4=0.10, historical=0.00)
    assert cfg.historical == 0.0


def test_sample_random_returns_random_player():
    cfg = _balanced_cfg(random=1.0, f1d2=0.0, f1d4=0.0, historical=0.0)
    pool = OpponentPool(cfg, dmc_agent_factory=None)
    pool.seed(0)
    p = pool.sample()
    assert isinstance(p, RandomPlayer)


def test_sample_f1d2_returns_greedy_depth2():
    cfg = _balanced_cfg(random=0.0, f1d2=1.0, f1d4=0.0, historical=0.0)
    pool = OpponentPool(cfg, dmc_agent_factory=None)
    pool.seed(0)
    p = pool.sample()
    assert isinstance(p, GreedyPlayer)
    assert p.cfg.depth == 2


def test_sample_f1d4_returns_greedy_depth4():
    cfg = _balanced_cfg(random=0.0, f1d2=0.0, f1d4=1.0, historical=0.0)
    pool = OpponentPool(cfg, dmc_agent_factory=None)
    pool.seed(0)
    p = pool.sample()
    assert isinstance(p, GreedyPlayer)
    assert p.cfg.depth == 4


def test_historical_cold_start_falls_back_to_random():
    """Empty ring + factory present: still falls back to RandomPlayer."""
    cfg = _balanced_cfg(random=0.0, f1d2=0.0, f1d4=0.0, historical=1.0)
    pool = OpponentPool(cfg, dmc_agent_factory=lambda sd: 'dmc_sentinel')
    pool.seed(0)
    p = pool.sample()
    assert isinstance(p, RandomPlayer)  # ring empty


def test_historical_returns_factory_built_after_snapshot():
    """Add a snapshot → historical sampling now hits the factory."""
    cfg = _balanced_cfg(random=0.0, f1d2=0.0, f1d4=0.0, historical=1.0)
    pool = OpponentPool(cfg, dmc_agent_factory=lambda sd: ('built', sd))
    pool.add_snapshot({'fake_state': 1})
    pool.seed(0)
    p = pool.sample()
    assert p == ('built', {'fake_state': 1})


def test_historical_ring_evicts_oldest_at_capacity():
    """ring_size=2: 3 adds → first one evicted."""
    cfg = _balanced_cfg(random=0.0, f1d2=0.0, f1d4=0.0, historical=1.0, ring_size=2)
    pool = OpponentPool(cfg, dmc_agent_factory=lambda sd: sd)
    pool.add_snapshot('A')
    pool.add_snapshot('B')
    pool.add_snapshot('C')
    assert list(pool._ring) == ['B', 'C']


def test_weighted_choice_proportions_within_tolerance():
    """Empirical sampling matches weights within ~2 std at N=2000."""
    cfg = _balanced_cfg(random=0.4, f1d2=0.4, f1d4=0.1, historical=0.1, ring_size=2)
    # Use factory to make 'historical' return distinct sentinel
    pool = OpponentPool(cfg, dmc_agent_factory=lambda sd: 'HIST')
    pool.add_snapshot({'sd': 1})
    pool.seed(42)
    N = 2000
    counts: Counter = Counter()
    for _ in range(N):
        p = pool.sample()
        if isinstance(p, RandomPlayer):
            counts['random'] += 1
        elif isinstance(p, GreedyPlayer):
            counts['f1d' + str(p.cfg.depth)] += 1
        elif p == 'HIST':
            counts['historical'] += 1
    # 2-sigma 上下: each weight has std = sqrt(w*(1-w)/N); 0.4 → ~0.011, so ±0.025
    assert abs(counts['random'] / N - 0.4) < 0.03
    assert abs(counts['f1d2'] / N - 0.4) < 0.03
    assert abs(counts['f1d4'] / N - 0.1) < 0.025
    assert abs(counts['historical'] / N - 0.1) < 0.025
