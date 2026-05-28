"""DMC transition payload wire format Python self-test + cross-lang schema drift 守门。

DMC 是当前唯一真有 Go-encode → Python-decode production flow 的 paradigm。 本测覆盖:
1. Python self encode→decode roundtrip(同 az/ppo test 风格)。
2. PayloadVer mismatch fail-loud(catch Go DmcPayloadVer 与 Python DMC_PAYLOAD_VER 漂移)。
3. byte-layout golden — hardcode 关键 offset 上的字节值,锁 schema:任何字段顺序 / 类型
   改动 → fixture 验证 mismatch → 强制开发者同步 bump version。

cross-lang Go→Python e2e bit-exact 验证由 gicg_actor/dmc/obs_encoder_test.go
TestEncodeDmcTransitionPayload_RoundTrip(Go side)+ 本文件 ver+golden(Python side)
共同守门。 改任一侧 layout 都至少一方 fail。
"""

from __future__ import annotations

import struct

import numpy as np
import pytest

from training.core.actor.transition_sink_wire import (
    DMC_PAYLOAD_VER,
    _DMC_PAYLOAD_HEADER_SIZE,
    decode_dmc_payload,
    encode_dmc_payload,
)


def test_dmc_payload_roundtrip_with_static():
    """First-transition-per-episode 路径:static 携带 raw int32 数组。"""
    dyn = np.array([1.5, -2.5, 3.0, 4.0], dtype=np.float32)
    refs = np.array([0, 1, 2, 3, 4, 5], dtype=np.int64)
    pay = np.array([0.1, 0.2, 0.3], dtype=np.float32)
    static = np.array([10, 20, 30, 40], dtype=np.int32)
    hash_ = bytes(range(16))

    blob = encode_dmc_payload(
        chosen_action=2,
        step_in_episode=17,
        reward=1.0,
        n_legal=4,
        static_hash=hash_,
        dyn_obs=dyn,
        refs=refs,
        pay=pay,
        static=static,
    )
    decoded = decode_dmc_payload(blob)

    assert decoded.chosen_action == 2
    assert decoded.step_in_episode == 17
    assert decoded.reward == pytest.approx(1.0)
    assert decoded.n_legal == 4
    assert decoded.static_hash == hash_
    np.testing.assert_array_equal(decoded.dyn_obs, dyn)
    np.testing.assert_array_equal(decoded.refs, refs)
    np.testing.assert_array_equal(decoded.pay, pay)
    np.testing.assert_array_equal(decoded.static, static)


def test_dmc_payload_roundtrip_no_static():
    """后续 transition:NStatic=0(走 hash cache)。"""
    blob = encode_dmc_payload(
        chosen_action=0,
        step_in_episode=1,
        reward=0.0,
        n_legal=1,
        static_hash=b'\xab' * 16,
        dyn_obs=np.zeros(3, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
    )
    decoded = decode_dmc_payload(blob)
    assert len(decoded.static) == 0


def test_dmc_payload_ver_mismatch_raises():
    """改 payload 首字节 (PayloadVer) → decode 必须 fail-loud。 这是 cross-lang
    schema drift safety net 的真实使用:Go DmcPayloadVer 与 Python DMC_PAYLOAD_VER
    不 lock-step 时第一时间 catch。"""
    blob = bytearray(
        encode_dmc_payload(
            chosen_action=0,
            step_in_episode=0,
            reward=0.0,
            n_legal=1,
            static_hash=b'\x00' * 16,
            dyn_obs=np.zeros(2, dtype=np.float32),
            refs=np.zeros(0, dtype=np.int64),
            pay=np.zeros(0, dtype=np.float32),
        )
    )
    blob[0] = 99  # 不存在的 future version
    with pytest.raises(ValueError, match='DMC payload version mismatch'):
        decode_dmc_payload(bytes(blob))


def test_dmc_payload_header_size_matches_go():
    """Layout size 跟 Go side DmcTransitionHeader binary.Size 一致(2026-05-28 = 49 byte)。

    DmcTransitionHeader: PayloadVer(1) + ChosenAction(4) + StepInEp(4) + RewardX1M(4) +
    5×u32 N* (20) + StaticHash(16) = 49 byte。
    """
    assert _DMC_PAYLOAD_HEADER_SIZE == 49


def test_dmc_payload_byte_layout_golden():
    """Byte-layout golden — 锁 Go wire format 字段顺序 + 偏移。

    任何字段顺序 / 类型改 → 本测 fail → 提醒开发者同步 bump DMC_PAYLOAD_VER + Go
    DmcPayloadVer + 修两侧 layout 文档。
    """
    # 已知 input:每字段取易识别值,避免歧义。
    blob = encode_dmc_payload(
        chosen_action=0xDEADBEEF & 0xFFFF,  # u32 fits
        step_in_episode=0x12345678,
        reward=-0.5,  # → int32(-500_000) = 0xFFF85EE0 (i32 little-endian)
        n_legal=42,
        static_hash=bytes(range(16)),  # 0x00..0x0F
        dyn_obs=np.array([1.0, 2.0], dtype=np.float32),
        refs=np.array([0x7FFFFFFFFFFFFFFF], dtype=np.int64),
        pay=np.array([], dtype=np.float32),
        static=np.array([], dtype=np.int32),
    )
    # 关键 offset 校验
    assert blob[0] == DMC_PAYLOAD_VER, 'PayloadVer must be at byte 0'
    assert struct.unpack_from('<I', blob, 1)[0] == 0xBEEF, 'ChosenAction at offset 1..5'
    assert struct.unpack_from('<I', blob, 5)[0] == 0x12345678, 'StepInEp at offset 5..9'
    assert struct.unpack_from('<i', blob, 9)[0] == int(-0.5 * 1e6), 'RewardX1M at offset 9..13'
    assert struct.unpack_from('<I', blob, 13)[0] == 42, 'NLegal at offset 13..17'
    assert struct.unpack_from('<I', blob, 17)[0] == 2, 'NDyn at offset 17..21 (len(dyn))'
    assert struct.unpack_from('<I', blob, 21)[0] == 1, 'NRefs at offset 21..25 (len(refs))'
    assert struct.unpack_from('<I', blob, 25)[0] == 0, 'NPay at offset 25..29 (len(pay))'
    assert struct.unpack_from('<I', blob, 29)[0] == 0, 'NStatic at offset 29..33 (len(static))'
    # StaticHash 在 33..49
    assert blob[33:49] == bytes(range(16)), 'StaticHash at offset 33..49'
    # body 紧随 header
    assert len(blob) == 49 + 2 * 4 + 1 * 8, 'body = 2 float32 + 1 int64 after 49-byte header'
