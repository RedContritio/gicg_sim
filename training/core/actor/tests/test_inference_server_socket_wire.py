"""I29 P1.3 — wire format Python side encoder/decoder unit tests。

守 round-trip + schema layout + boundary case。 Cross-language equivalence with Go side
留 P1.3b 集成时端到端验(预先在 Mac 端跑 Go side encode 写 bytes file → Python decode 读
对照),本测试仅 Python side self-consistency。
"""

from __future__ import annotations

import io
import struct
from pathlib import Path  # noqa: F401 — kept for future cross-lang test

import numpy as np
import pytest

from training.core.actor.inference_server_socket_wire import (
    HEADER_SIZE,
    INFER_STATUS_ERR,
    INFER_STATUS_OK,
    MAX_MESSAGE_BYTES,
    RESPONSE_HEADER_SIZE,
    STATIC_HASH_SIZE,
    WIRE_VERSION,
    InferRequest,
    InferResponse,
    decode_infer_request,
    decode_infer_response,
    encode_infer_request,
    encode_infer_response,
    read_length_prefixed,
)


def test_encode_decode_request_round_trip():
    """Round-trip bit-exact:encode → decode 后字段全相等。"""
    orig = InferRequest(
        static_hash=bytes(range(16)),
        client_id=42,
        req_id=1337,
        dyn_obs=np.array([1.5, -2.5, 0.0, 3.14159], dtype=np.float32),
        refs=np.array([0, -1, 1 << 40, 9999], dtype=np.int64),
        pay=np.array([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
        static=np.array([7, -1, 1 << 20], dtype=np.int32),
    )
    encoded = encode_infer_request(orig)
    # Outer length prefix is first 4 bytes,payload follows。
    assert len(encoded) >= 4
    payload = encoded[4:]
    decoded = decode_infer_request(payload)

    assert decoded.static_hash == orig.static_hash
    assert decoded.client_id == orig.client_id
    assert decoded.req_id == orig.req_id
    assert np.array_equal(decoded.dyn_obs, orig.dyn_obs)
    assert np.array_equal(decoded.refs, orig.refs)
    assert np.array_equal(decoded.pay, orig.pay)
    assert np.array_equal(decoded.static, orig.static)


def test_encode_request_empty_arrays():
    """Nil / empty arrays encode 不 panic + decode 还原成 0-length。"""
    orig = InferRequest(
        static_hash=b'\x00' * 16,
        client_id=1,
        req_id=1,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
        static=np.zeros(0, dtype=np.int32),
    )
    encoded = encode_infer_request(orig)
    expected_len = 4 + HEADER_SIZE  # outer prefix + header,0 data bytes
    assert len(encoded) == expected_len
    decoded = decode_infer_request(encoded[4:])
    assert len(decoded.dyn_obs) == 0
    assert len(decoded.refs) == 0
    assert len(decoded.pay) == 0


def test_decode_request_wrong_version_raises():
    """Schema version mismatch fail loud。"""
    payload = bytearray(HEADER_SIZE)
    struct.pack_into('<H', payload, 0, 999)  # ver=999 != 1
    with pytest.raises(ValueError, match='wire version'):
        decode_infer_request(bytes(payload))


def test_encode_decode_response_ok():
    """status=ok 路径 round-trip float32 bit-exact。"""
    orig = InferResponse(
        status=INFER_STATUS_OK,
        logits=np.array([0.1, -0.2, 1e10, -1e10], dtype=np.float32),
    )
    encoded = encode_infer_response(orig)
    decoded = decode_infer_response(encoded[4:])
    assert decoded.status == INFER_STATUS_OK
    assert np.array_equal(decoded.logits, orig.logits)


def test_encode_decode_response_err():
    """status=err 路径 ErrMsg UTF-8 round-trip。"""
    orig = InferResponse(status=INFER_STATUS_ERR, err_msg='test error 中文 ε失败')
    encoded = encode_infer_response(orig)
    decoded = decode_infer_response(encoded[4:])
    assert decoded.status == INFER_STATUS_ERR
    assert decoded.err_msg == orig.err_msg


def test_read_length_prefixed_full_message():
    """read_length_prefixed 路径 ok — outer 4-byte prefix + payload。"""
    req = InferRequest(
        static_hash=b'\xaa' * 16,
        client_id=1,
        req_id=2,
        dyn_obs=np.array([1.0, 2.0, 3.0], dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
        static=np.zeros(0, dtype=np.int32),
    )
    encoded = encode_infer_request(req)
    reader = io.BytesIO(encoded)
    payload = read_length_prefixed(reader)
    decoded = decode_infer_request(payload)
    assert decoded.client_id == 1
    assert decoded.req_id == 2


def test_read_length_prefixed_oversized_rejected():
    """Malformed length(> MAX_MESSAGE_BYTES)fail loud 防 DoS。"""
    huge = struct.pack('<I', MAX_MESSAGE_BYTES + 1)
    reader = io.BytesIO(huge)
    with pytest.raises(ValueError, match='exceeds cap'):
        read_length_prefixed(reader)


def test_read_length_prefixed_short_read_raises():
    """Truncated stream → EOFError(防 TCP coalescing 切分时漏 read)。"""
    # 4-byte len = 100,but actual payload is only 50 bytes:
    truncated = struct.pack('<I', 100) + b'\x00' * 50
    reader = io.BytesIO(truncated)
    with pytest.raises(EOFError, match='short read'):
        read_length_prefixed(reader)


def test_encode_request_bad_static_hash_size():
    """static_hash 长度不为 16 fail loud。"""
    req = InferRequest(
        static_hash=b'\x00' * 8,  # 8 bytes,not 16
        client_id=1,
        req_id=1,
        dyn_obs=np.zeros(0, dtype=np.float32),
        refs=np.zeros(0, dtype=np.int64),
        pay=np.zeros(0, dtype=np.float32),
        static=np.zeros(0, dtype=np.int32),
    )
    with pytest.raises(ValueError, match='static_hash must be 16'):
        encode_infer_request(req)


def test_decode_response_unknown_status_raises():
    """Unknown status byte → fail loud(防 Go side ship 新 status forget 同步 Python)。"""
    payload = bytes([99]) + struct.pack('<H', 0)
    with pytest.raises(ValueError, match='unknown response status'):
        decode_infer_response(payload)


def test_constants_match_go_layout():
    """Layout sizes 跟 Go side ``HeaderSize`` / ``ResponseHeaderSize`` 一致 — 防 future
    drift 时一边改一边漏。"""
    # Layout sizes 跟 Go side ``HeaderSize`` / ``ResponseHeaderSize`` 一致 — 防 future
    # drift。 v2 schema u32 array lens: header = 2+16+4+4+4+4+4+4 = 42 bytes。
    assert HEADER_SIZE == 42
    assert RESPONSE_HEADER_SIZE == 3
    assert STATIC_HASH_SIZE == 16
    assert WIRE_VERSION == 2
    assert INFER_STATUS_OK == 0
    assert INFER_STATUS_ERR == 1
