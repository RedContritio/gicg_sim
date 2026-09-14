"""Opponent coverage, frozen schedules and exact sampling-state restore."""

import copy
import pytest
from tools.experiments.league.pool import LeaguePool, pfsp


def make_pool():
    entries = [{'id': 'a', 'weight': 0.3}, {'id': 'b', 'weight': 0.7}]
    return LeaguePool(entries, {'a': lambda s: ('a', s), 'b': lambda s: ('b', s)}, 51, 'plan')


def test_pfsp_covers_all_and_prefers_weaknesses():
    weights = pfsp([0, 0.5, 1])
    assert sum(weights) == pytest.approx(1)
    assert weights[0] > weights[1] > weights[2] > 0


@pytest.mark.parametrize('scores', [[], [-0.1], [1.1], [float('nan')]])
def test_pfsp_rejects_invalid_measurements(scores):
    with pytest.raises(ValueError):
        pfsp(scores)


def test_pool_resume_preserves_draw_sequence_and_counts():
    pool = make_pool()
    for _ in range(11):
        pool.sample()
    saved = pool.state_dict()
    expected = [pool.sample() for _ in range(50)]
    resumed = make_pool()
    resumed.load_state_dict(saved)
    assert [resumed.sample() for _ in range(50)] == expected
    assert resumed.draws == pool.draws


def test_pool_rejects_silent_opponent_or_plan_change():
    pool = make_pool()
    saved = pool.state_dict()
    for key, value in [('identity', 'other'), ('entries', [{'id': 'a', 'weight': 1}])]:
        bad = copy.deepcopy(saved)
        bad[key] = value
        with pytest.raises(ValueError):
            pool.load_state_dict(bad)


def test_pool_snapshot_does_not_alias_live_metadata():
    pool = make_pool()
    state = pool.state_dict()
    state['entries'][0]['weight'] = 100
    assert pool.entries[0]['weight'] == 0.3
