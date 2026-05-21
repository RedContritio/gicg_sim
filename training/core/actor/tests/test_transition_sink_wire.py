"""Python side wire format roundtrip + cross-lang compat smoke。

cross-lang test (Go encode → Python decode) 走 e2e Mac smoke + P1.5 Win box stress。
本测仅 Python self encode/decode roundtrip。
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from training.core.actor.transition_sink_wire import (
    Transition,
    decode_dmc_payload,
    decode_transition,
    encode_dmc_payload,
    encode_transition,
)


def test_transition_envelope_roundtrip():
    t = Transition(client_id=42, episode_id=7, step=123, done=True, payload=b'\x01\x02\x03\x04')
    encoded = encode_transition(t)
    (outer_len,) = struct.unpack_from('<I', encoded, 0)
    body = encoded[4 : 4 + outer_len]
    assert len(body) == outer_len
    decoded = decode_transition(body)
    assert decoded.client_id == 42
    assert decoded.episode_id == 7
    assert decoded.step == 123
    assert decoded.done is True
    assert decoded.payload == b'\x01\x02\x03\x04'


def test_transition_envelope_done_false():
    t = Transition(client_id=0, episode_id=0, step=0, done=False, payload=b'')
    encoded = encode_transition(t)
    (outer_len,) = struct.unpack_from('<I', encoded, 0)
    decoded = decode_transition(encoded[4 : 4 + outer_len])
    assert decoded.done is False
    assert decoded.payload == b''


def test_decode_transition_version_mismatch():
    bad = struct.pack('<H', 99) + struct.pack('<III', 1, 2, 3) + struct.pack('<BB', 0, 0) + struct.pack('<I', 0)
    with pytest.raises(ValueError, match='wire version mismatch'):
        decode_transition(bad)


def test_decode_transition_short_payload():
    with pytest.raises(ValueError, match='< header'):
        decode_transition(b'\x01\x02\x03')


def test_dmc_payload_roundtrip_with_static():
    """First-transition-per-episode 路径:静态 obs raw 也带在 payload 里。"""
    dyn = np.array([1.5, -2.25, 3.75, 0.0], dtype=np.float32)
    refs = np.array([0, 1, 2, 3, 4, 5], dtype=np.int64)
    pay = np.array([0.1, 0.2], dtype=np.float32)
    static = np.array([10, 20, 30], dtype=np.int32)
    hash_ = bytes(range(16))
    blob = encode_dmc_payload(
        chosen_action=5,
        step_in_episode=17,
        reward=1.0,
        n_legal=4,
        static_hash=hash_,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
        static=static,
    )
    decoded = decode_dmc_payload(blob, dyn_obs_len=4)
    assert decoded.chosen_action == 5
    assert decoded.step_in_episode == 17
    assert decoded.reward == pytest.approx(1.0)
    assert decoded.n_legal == 4
    assert decoded.static_hash == hash_
    np.testing.assert_array_equal(decoded.dyn_obs, dyn)
    np.testing.assert_array_equal(decoded.refs, refs)
    np.testing.assert_array_equal(decoded.pay, pay)
    np.testing.assert_array_equal(decoded.static, static)


def test_dmc_payload_roundtrip_no_static():
    """后续 transition 路径:NStatic=0,collector 走 cache by static_hash。"""
    dyn = np.zeros(3, dtype=np.float32)
    refs = np.zeros(0, dtype=np.int64)
    pay = np.zeros(0, dtype=np.float32)
    hash_ = b'\xab' * 16
    blob = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=1,
        reward=0.0,
        n_legal=1,
        static_hash=hash_,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
        # static omitted → defaults to empty
    )
    decoded = decode_dmc_payload(blob)
    assert decoded.static_hash == hash_
    assert len(decoded.static) == 0


def test_dmc_payload_negative_reward():
    blob = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=-1.0,
        n_legal=1,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(2, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    decoded = decode_dmc_payload(blob)
    assert decoded.reward == pytest.approx(-1.0)


def test_dmc_payload_zero_arrays():
    blob = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    decoded = decode_dmc_payload(blob)
    assert len(decoded.dyn_obs) == 0
    assert len(decoded.refs) == 0
    assert len(decoded.pay) == 0
    assert len(decoded.static) == 0


def test_dmc_payload_len_mismatch():
    blob = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(3, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    with pytest.raises(ValueError, match='dyn_obs len 3'):
        decode_dmc_payload(blob, dyn_obs_len=5)


def test_dmc_payload_truncated_body_raises():
    """Payload 比 header counts 暗示的尺寸短 → fail loud。"""
    blob = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(3, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    truncated = blob[:-4]  # drop last 4 bytes(1 dyn entry)
    with pytest.raises(ValueError, match='payload len'):
        decode_dmc_payload(truncated)
