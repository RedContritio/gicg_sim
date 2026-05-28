"""PPO transition payload wire format roundtrip + cross-lang compat verification。"""

from __future__ import annotations

import numpy as np
import pytest

from training.core.actor.transition_sink_wire import (
    decode_ppo_payload,
    encode_ppo_payload,
)


def test_ppo_payload_roundtrip():
    """First-transition path:static + 全字段。"""
    dyn = np.array([1.5, -2.5, 3.0, 4.0], dtype=np.float32)
    refs = np.array([0, 1, 2, 3, 4, 5], dtype=np.int64)
    pay = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    static = np.array([10, 20, 30, 40], dtype=np.int32)
    hash_ = bytes(range(16))

    blob = encode_ppo_payload(
        chosen_action=3,
        step_in_episode=25,
        reward=0.5,
        log_prob=-1.23,
        value=0.66,
        n_legal=4,
        static_hash=hash_,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
        static=static,
    )
    decoded = decode_ppo_payload(blob)

    assert decoded.chosen_action == 3
    assert decoded.step_in_episode == 25
    assert decoded.reward == pytest.approx(0.5)
    assert decoded.log_prob == pytest.approx(-1.23)
    assert decoded.value == pytest.approx(0.66)
    assert decoded.n_legal == 4
    assert decoded.static_hash == hash_
    np.testing.assert_array_equal(decoded.dyn_obs, dyn)
    np.testing.assert_array_equal(decoded.refs, refs)
    np.testing.assert_array_equal(decoded.pay, pay)
    np.testing.assert_array_equal(decoded.static, static)


def test_ppo_payload_roundtrip_no_static():
    """后续 transition 路径:NStatic=0 走 cache by hash。"""
    blob = encode_ppo_payload(
        chosen_action=0,
        step_in_episode=1,
        reward=0.0,
        log_prob=0.0,
        value=0.0,
        n_legal=1,
        static_hash=b'\xab' * 16,
        dyn_obs=np.zeros(3, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    decoded = decode_ppo_payload(blob)
    assert len(decoded.static) == 0


def test_ppo_payload_negative_log_prob_value():
    """log_prob 通常 < 0(uniform π:log(1/30) ≈ -3.4),value 可负。"""
    blob = encode_ppo_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        log_prob=-3.4,
        value=-0.5,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    decoded = decode_ppo_payload(blob)
    assert decoded.log_prob == pytest.approx(-3.4)
    assert decoded.value == pytest.approx(-0.5)


def test_ppo_payload_truncated_raises():
    blob = encode_ppo_payload(
        chosen_action=0,
        step_in_episode=0,
        reward=0.0,
        log_prob=0.0,
        value=0.0,
        n_legal=0,
        static_hash=b'\x00' * 16,
        dyn_obs=np.zeros(3, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    truncated = blob[:-4]
    with pytest.raises(ValueError, match='payload len'):
        decode_ppo_payload(truncated)


def test_ppo_payload_ver_mismatch_raises():
    """改 payload 首字节 (PayloadVer) → decode 必须 fail-loud。 守 cross-lang
    schema drift safety net:Go PpoPayloadVer 与 Python PPO_PAYLOAD_VER 不 lock-step
    时第一时间 catch。"""
    blob = bytearray(
        encode_ppo_payload(
            chosen_action=0,
            step_in_episode=0,
            reward=0.0,
            log_prob=0.0,
            value=0.0,
            n_legal=1,
            static_hash=b'\x00' * 16,
            dyn_obs=np.zeros(2, dtype=np.float32),
            refs=np.zeros(0, dtype=np.int64),
            pay=np.zeros(0, dtype=np.float32),
        )
    )
    blob[0] = 99
    with pytest.raises(ValueError, match='PPO payload version mismatch'):
        decode_ppo_payload(bytes(blob))


def test_ppo_payload_header_size_matches_go():
    """Layout size 跟 Go side PpoTransitionHeader binary.Size 一致(57 byte post 2026-05-28)。

    PpoTransitionHeader:PayloadVer(1) + ChosenAction(4) + StepInEp(4) + RewardX1M(4) +
    LogProbX1M(4) + ValueX1M(4) + 5×u32 N* (20) + StaticHash(16) = 57 byte。
    """
    from training.core.actor.transition_sink_wire import _PPO_PAYLOAD_HEADER_SIZE

    assert _PPO_PAYLOAD_HEADER_SIZE == 57
