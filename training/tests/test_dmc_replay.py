"""Contract tests for DMC replay buffer — FIFO + sampling.

DmcReplayBuffer + DmcTransition relocated from ``legacy/replay.py`` to
``training/paradigms/dmc/buffer.py`` in FU-W4-DMC.
"""

from __future__ import annotations

import pytest

from training.paradigms.dmc.buffer import DmcReplayBuffer, DmcTransition


def _trans(action_idx: int) -> DmcTransition:
    return DmcTransition(obs_dict={'k': action_idx}, action_idx=action_idx, G=0.0)


def test_push_episode_backfills_G_on_all_transitions():
    """G is set on every transition at push time, not at construction."""
    buf = DmcReplayBuffer(capacity=10, seed=0)
    ts = [_trans(i) for i in range(3)]
    for t in ts:
        assert t.G == 0.0
    buf.push_episode(ts, G=1.0)
    for t in ts:
        assert t.G == 1.0
    assert len(buf) == 3


def test_push_negative_G_backfills_minus_one():
    buf = DmcReplayBuffer(capacity=10, seed=0)
    ts = [_trans(0), _trans(1)]
    buf.push_episode(ts, G=-1.0)
    assert all(t.G == -1.0 for t in ts)


def test_fifo_eviction_on_overflow():
    """deque(maxlen=cap) drops oldest when full."""
    buf = DmcReplayBuffer(capacity=3, seed=0)
    buf.push_episode([_trans(0)], G=1.0)
    buf.push_episode([_trans(1)], G=1.0)
    buf.push_episode([_trans(2)], G=1.0)
    buf.push_episode([_trans(3)], G=1.0)
    assert len(buf) == 3
    actions = [t.action_idx for t in buf.buf]
    assert actions == [1, 2, 3]


def test_total_seen_counts_all_pushes_including_evicted():
    buf = DmcReplayBuffer(capacity=2, seed=0)
    for i in range(5):
        buf.push_episode([_trans(i)], G=1.0)
    assert len(buf) == 2
    assert buf.total_seen == 5


def test_sample_size_equals_request():
    buf = DmcReplayBuffer(capacity=10, seed=0)
    buf.push_episode([_trans(i) for i in range(5)], G=1.0)
    out = buf.sample(3)
    assert len(out) == 3


def test_sample_without_replacement():
    """Sample 5 from buffer of 5 → all distinct (action_idx is unique)."""
    buf = DmcReplayBuffer(capacity=10, seed=42)
    buf.push_episode([_trans(i) for i in range(5)], G=1.0)
    out = buf.sample(5)
    assert len({t.action_idx for t in out}) == 5


def test_sample_raises_when_request_exceeds_buffer():
    buf = DmcReplayBuffer(capacity=10, seed=0)
    buf.push_episode([_trans(0), _trans(1)], G=1.0)
    with pytest.raises(ValueError, match='requested 5 but'):
        buf.sample(5)


def test_sample_is_deterministic_per_seed():
    """Two buffers with same seed see same population → sample() identical."""
    buf_a = DmcReplayBuffer(capacity=10, seed=7)
    buf_b = DmcReplayBuffer(capacity=10, seed=7)
    for buf in (buf_a, buf_b):
        buf.push_episode([_trans(i) for i in range(5)], G=1.0)
    out_a = [t.action_idx for t in buf_a.sample(3)]
    out_b = [t.action_idx for t in buf_b.sample(3)]
    assert out_a == out_b


def test_clear_resets_length_but_not_total_seen():
    buf = DmcReplayBuffer(capacity=10, seed=0)
    buf.push_episode([_trans(0), _trans(1)], G=1.0)
    assert len(buf) == 2
    buf.clear()
    assert len(buf) == 0
    # total_seen is monotonic cumulative count
    assert buf.total_seen == 2
