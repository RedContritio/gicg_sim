"""Python side wire format roundtrip + cross-lang compat smoke。

cross-lang test 在 ``test_transition_sink_listener_e2e.py`` 起 Python listener +
让 Go side encode 推 transition 跑 e2e。 本测仅 Python self-encode/decode。
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from training.core.actor.transition_sink_wire import (
    DmcTransitionPayload,
    Transition,
    decode_dmc_payload,
    decode_transition,
    encode_transition,
)


def test_transition_envelope_roundtrip():
    t = Transition(client_id=42, episode_id=7, step=123, done=True, payload=b'\x01\x02\x03\x04')
    encoded = encode_transition(t)
    # outer length prefix → strip first 4 bytes, decode rest
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
    # Manually construct payload with wrong wire version
    bad = struct.pack('<H', 99) + struct.pack('<III', 1, 2, 3) + struct.pack('<BB', 0, 0) + struct.pack('<I', 0)
    with pytest.raises(ValueError, match='wire version mismatch'):
        decode_transition(bad)


def test_decode_transition_short_payload():
    with pytest.raises(ValueError, match='< header'):
        decode_transition(b'\x01\x02\x03')


def test_dmc_payload_roundtrip():
    dyn = np.array([1.5, -2.25, 3.75, 0.0], dtype=np.float32)
    blob = (
        struct.pack('<II', 5, 17)  # chosen, step_in_ep
        + struct.pack('<i', 1_000_000)  # reward=1.0 fixed-point
        + dyn.tobytes()
    )
    decoded = decode_dmc_payload(blob, dyn_obs_len=4)
    assert decoded.chosen_action == 5
    assert decoded.step_in_episode == 17
    assert decoded.reward == pytest.approx(1.0)
    np.testing.assert_array_equal(decoded.dyn_obs, dyn)


def test_dmc_payload_negative_reward():
    blob = struct.pack('<II', 0, 0) + struct.pack('<i', -1_000_000) + np.zeros(2, dtype=np.float32).tobytes()
    decoded = decode_dmc_payload(blob)
    assert decoded.reward == pytest.approx(-1.0)


def test_dmc_payload_zero_dyn_obs():
    blob = struct.pack('<II', 0, 0) + struct.pack('<i', 0)
    decoded = decode_dmc_payload(blob)
    assert len(decoded.dyn_obs) == 0


def test_dmc_payload_len_mismatch():
    blob = struct.pack('<II', 0, 0) + struct.pack('<i', 0) + np.zeros(3, dtype=np.float32).tobytes()
    with pytest.raises(ValueError, match='dyn_obs len 3'):
        decode_dmc_payload(blob, dyn_obs_len=5)


def test_dmc_payload_misaligned_dyn_bytes():
    # 5 bytes after header → not multiple of 4
    blob = struct.pack('<II', 0, 0) + struct.pack('<i', 0) + b'\x00\x01\x02\x03\x04'
    with pytest.raises(ValueError, match='not multiple of 4'):
        decode_dmc_payload(blob)
