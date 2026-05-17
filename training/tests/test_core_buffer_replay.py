"""Buffer impls — push / sample / clear / state_dict roundtrip."""

from __future__ import annotations

import numpy as np
import pytest

from training.core.buffer.dataset import DatasetBuffer
from training.core.buffer.replay import ReplayBuffer
from training.core.buffer.reservoir import ReservoirBuffer
from training.core.buffer.rollout import RolloutBuffer
from training.core.buffer.shared import SHMRingBuffer
from training.core.protocols import CollectorOutput, Transition


def _make_transitions(n: int) -> list:
    return [Transition(obs=None, action=i, legal_mask=None, reward=float(i), done=False) for i in range(n)]


def _wrap(transitions) -> CollectorOutput:
    return CollectorOutput(
        transitions=transitions,
        episode_stats=[{'len': len(transitions)}],
        n_units=len(transitions),
    )


# ---------- ReplayBuffer ---------- #


def test_replay_push_sample():
    buf = ReplayBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(10)))
    assert len(buf) == 10
    batch = buf.sample(batch_size=4, rng=np.random.default_rng(0))
    assert batch.size == 4
    assert len(batch.data['transitions']) == 4


def test_replay_capacity_eviction():
    buf = ReplayBuffer(capacity=5)
    buf.push(_wrap(_make_transitions(10)))
    assert len(buf) == 5


def test_replay_sample_too_few_raises():
    buf = ReplayBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(3)))
    with pytest.raises(ValueError, match='< batch_size'):
        buf.sample(batch_size=4)


def test_replay_state_dict_roundtrip():
    buf = ReplayBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(10)))
    sd = buf.state_dict()
    buf2 = ReplayBuffer(capacity=20)
    buf2.load_state_dict(sd)
    assert len(buf2) == 10


def test_replay_load_state_dict_capacity_mismatch_raises():
    buf = ReplayBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(5)))
    sd = buf.state_dict()
    buf2 = ReplayBuffer(capacity=10)  # different
    with pytest.raises(ValueError, match='capacity mismatch'):
        buf2.load_state_dict(sd)


def test_replay_clear():
    buf = ReplayBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(5)))
    buf.clear()
    assert len(buf) == 0


# ---------- ReservoirBuffer ---------- #


def test_reservoir_push_and_sample():
    buf = ReservoirBuffer(capacity=50)
    buf.push(_wrap(_make_transitions(100)))
    assert len(buf) == 50
    batch = buf.sample(batch_size=8, rng=np.random.default_rng(0))
    assert batch.size == 8


def test_reservoir_state_dict():
    buf = ReservoirBuffer(capacity=10)
    buf.push(_wrap(_make_transitions(20)))
    sd = buf.state_dict()
    buf2 = ReservoirBuffer(capacity=10)
    buf2.load_state_dict(sd)
    assert len(buf2) == 10


# ---------- RolloutBuffer ---------- #


def test_rollout_capacity_overflow_raises():
    buf = RolloutBuffer(capacity=5)
    buf.push(_wrap(_make_transitions(5)))
    with pytest.raises(RuntimeError, match='over capacity'):
        buf.push(_wrap(_make_transitions(1)))


def test_rollout_clear():
    buf = RolloutBuffer(capacity=5)
    buf.push(_wrap(_make_transitions(3)))
    buf.clear()
    assert len(buf) == 0


# ---------- DatasetBuffer ---------- #


def test_dataset_overflow_raises():
    buf = DatasetBuffer(capacity=3)
    with pytest.raises(RuntimeError, match='over capacity'):
        buf.push(_wrap(_make_transitions(10)))


def test_dataset_sample():
    buf = DatasetBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(15)))
    batch = buf.sample(batch_size=4, rng=np.random.default_rng(0))
    assert batch.size == 4


# ---------- SHMRingBuffer ---------- #


def test_shm_buffer_push_sample():
    buf = SHMRingBuffer(capacity=20)
    buf.push(_wrap(_make_transitions(15)))
    batch = buf.sample(batch_size=5, rng=np.random.default_rng(0))
    assert batch.size == 5


def test_buffer_zero_capacity_raises():
    with pytest.raises(ValueError, match='capacity must'):
        ReplayBuffer(capacity=0)
