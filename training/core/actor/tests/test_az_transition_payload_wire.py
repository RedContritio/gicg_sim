"""AZ transition payload wire format roundtrip + cross-lang compat verification。

cross-lang(Go encode → Python decode)走 P2.X 完成 AZ Run loop ship 时 e2e。 本测仅
Python self encode/decode roundtrip。
"""

from __future__ import annotations

import numpy as np
import pytest

from training.core.actor.az_transition_payload_wire import (
    decode_az_payload,
    encode_az_payload,
)


def test_az_payload_roundtrip_with_visits_and_static():
    """First-transition-per-episode 路径:visits + static 都带。"""
    dyn = np.array([1.5, -2.5, 3.0, 4.0], dtype=np.float32)
    refs = np.array([0, 1, 2, 3, 4, 5], dtype=np.int64)
    pay = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    static = np.array([10, 20, 30, 40], dtype=np.int32)
    visits = np.array([0.5, 0.3, 0.15, 0.05], dtype=np.float32)
    hash_ = bytes(range(16))

    blob = encode_az_payload(
        chosen_action=2,
        step_in_episode=17,
        reward=1.0,
        root_value=0.42,
        n_legal=4,
        static_hash=hash_,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
        static=static,
        visits=visits,
    )
    decoded = decode_az_payload(blob)

    assert decoded.chosen_action == 2
    assert decoded.step_in_episode == 17
    assert decoded.reward == pytest.approx(1.0)
    assert decoded.root_value == pytest.approx(0.42)
    assert decoded.n_legal == 4
    assert decoded.static_hash == hash_
    np.testing.assert_array_equal(decoded.dyn_obs, dyn)
    np.testing.assert_array_equal(decoded.refs, refs)
    np.testing.assert_array_equal(decoded.pay, pay)
    np.testing.assert_array_equal(decoded.static, static)
    np.testing.assert_array_equal(decoded.visits, visits)


def test_az_payload_roundtrip_no_static_no_visits():
    """后续 transition 路径:NStatic=0(走 cache);Phase-1 stub 无 visits 也支持。"""
    dyn = np.zeros(3, dtype=np.float32)
    refs = np.zeros(0, dtype=np.int64)
    pay = np.zeros(0, dtype=np.float32)
    blob = encode_az_payload(
        chosen_action=0,
        step_in_episode=1,
        reward=0.0,
        root_value=0.0,
        n_legal=1,
        static_hash=b'\xab' * 16,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
    )
    decoded = decode_az_payload(blob)
    assert len(decoded.static) == 0
    assert len(decoded.visits) == 0


def test_az_payload_negative_root_value():
    """root_value can be negative(MCTS 学到不利 state)。"""
    blob = encode_az_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        root_value=-0.7,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    decoded = decode_az_payload(blob)
    assert decoded.root_value == pytest.approx(-0.7)


def test_az_payload_truncated_raises():
    blob = encode_az_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        root_value=0.0,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(3, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    truncated = blob[:-4]
    with pytest.raises(ValueError, match='payload len'):
        decode_az_payload(truncated)


def test_az_payload_ver_mismatch_raises():
    """改 payload 首字节 (PayloadVer) → decode 必须 fail-loud。 守 cross-lang
    schema drift safety net:Go AzPayloadVer 与 Python AZ_PAYLOAD_VER 不 lock-step
    时第一时间 catch。"""
    blob = bytearray(
        encode_az_payload(
            chosen_action=0,
            step_in_episode=0,
            reward=0.0,
            root_value=0.0,
            n_legal=1,
            static_hash=b'\x00' * 16,
            dyn_obs=np.zeros(2, dtype=np.float32),
            refs=np.zeros(0, dtype=np.int64),
            pay=np.zeros(0, dtype=np.float32),
        )
    )
    blob[0] = 99  # bump 到一个 invalid version
    with pytest.raises(ValueError, match='AZ payload version mismatch'):
        decode_az_payload(bytes(blob))


def test_az_payload_header_size_matches_go():
    """Layout size 跟 Go side AzTransitionHeader binary.Size 一致。

    AzTransitionHeader: PayloadVer(1) + ChosenAction(4) + StepInEp(4) + RewardX1M(4) +
    RootValueX1M(4) + 6×u32 N* (24) + StaticHash(16) = 57 byte (2026-05-28 加 PayloadVer)。
    """
    from training.core.actor.az_transition_payload_wire import _AZ_PAYLOAD_HEADER_SIZE

    assert _AZ_PAYLOAD_HEADER_SIZE == 57
