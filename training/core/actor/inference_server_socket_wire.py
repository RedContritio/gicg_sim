"""Python side wire format for Go actor ↔ Python InferenceServer socket protocol。

Mirror Go ``gicg_actor/wire_format.go`` 1:1 — same little-endian byte layout,无 pickle
overhead,zero-copy via ``np.frombuffer`` view。 schema 详 design.md D5 + 实测 < 1μs RTT
(IPC research agent 2026-05-21 验证)。

Wire format(inference request):

    [u16 ver][16B static_hash][u32 client_id][u32 req_id]
    [u16 n_dyn_f32][u16 n_refs_i64][u16 n_pay_f32]
    | dyn_obs (n_dyn_f32 × 4 bytes) | refs (n_refs_i64 × 8 bytes) | pay (n_pay_f32 × 4 bytes)

Wire format(inference response):

    [u8 status (0=ok, 1=err)][u16 n_logits_f32]
    | logits (n_logits_f32 × 4 bytes)  // status=0 case
    | err_msg bytes (no null terminator) // status=1 case

Outer frame:``[u32 len_le][payload bytes]``,reader 先 read 4-byte len 决定 recv_into buf size。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

WIRE_VERSION = 1
STATIC_HASH_SIZE = 16
MAX_MESSAGE_BYTES = 16 * 1024 * 1024  # 16 MB defense against malformed length
INFER_STATUS_OK = 0
INFER_STATUS_ERR = 1
HEADER_SIZE = 2 + 16 + 4 + 4 + 2 + 2 + 2  # 32 bytes fixed
RESPONSE_HEADER_SIZE = 1 + 2  # 3 bytes fixed


@dataclass
class InferRequest:
    """Decoded request from Go actor。 dyn_obs/refs/pay are numpy view of buf(no copy)。"""

    static_hash: bytes
    client_id: int
    req_id: int
    dyn_obs: np.ndarray  # float32 shape (n_dyn,)
    refs: np.ndarray  # int64 shape (n_refs,)
    pay: np.ndarray  # float32 shape (n_pay,)


@dataclass
class InferResponse:
    status: int
    logits: Optional[np.ndarray] = None  # float32 shape (n_logits,) when status=OK
    err_msg: str = ''


def encode_infer_request(req: InferRequest) -> bytes:
    """Serialize InferRequest 含 outer length prefix。 mirror Go EncodeInferRequest。"""
    if len(req.static_hash) != STATIC_HASH_SIZE:
        raise ValueError(f'static_hash must be {STATIC_HASH_SIZE} bytes, got {len(req.static_hash)}')
    dyn_bytes = req.dyn_obs.astype(np.float32, copy=False).tobytes()
    refs_bytes = req.refs.astype(np.int64, copy=False).tobytes()
    pay_bytes = req.pay.astype(np.float32, copy=False).tobytes()
    n_dyn = len(req.dyn_obs)
    n_refs = len(req.refs)
    n_pay = len(req.pay)
    if max(n_dyn, n_refs, n_pay) > 0xFFFF:
        raise ValueError(f'array len > u16 max(n_dyn={n_dyn} n_refs={n_refs} n_pay={n_pay})')
    payload_len = HEADER_SIZE + len(dyn_bytes) + len(refs_bytes) + len(pay_bytes)
    parts = [
        struct.pack('<I', payload_len),
        struct.pack('<H', WIRE_VERSION),
        req.static_hash,
        struct.pack('<II', req.client_id, req.req_id),
        struct.pack('<HHH', n_dyn, n_refs, n_pay),
        dyn_bytes,
        refs_bytes,
        pay_bytes,
    ]
    return b''.join(parts)


def decode_infer_request(payload: bytes) -> InferRequest:
    """Deserialize InferRequest payload(不含 outer length prefix)。 mirror Go
    DecodeInferRequest。 numpy arrays are read-only views into ``payload``(zero-copy)。
    """
    if len(payload) < HEADER_SIZE:
        raise ValueError(f'payload {len(payload)} byte < header {HEADER_SIZE}')
    (ver,) = struct.unpack_from('<H', payload, 0)
    if ver != WIRE_VERSION:
        raise ValueError(f'wire version mismatch: got {ver}, want {WIRE_VERSION}')
    static_hash = bytes(payload[2:18])
    client_id, req_id = struct.unpack_from('<II', payload, 18)
    n_dyn, n_refs, n_pay = struct.unpack_from('<HHH', payload, 26)
    expected_len = HEADER_SIZE + n_dyn * 4 + n_refs * 8 + n_pay * 4
    if len(payload) != expected_len:
        raise ValueError(
            f'payload len {len(payload)} != expected {expected_len} (n_dyn={n_dyn} n_refs={n_refs} n_pay={n_pay})'
        )
    off = HEADER_SIZE
    dyn_obs = np.frombuffer(payload, dtype=np.float32, count=n_dyn, offset=off)
    off += n_dyn * 4
    refs = np.frombuffer(payload, dtype=np.int64, count=n_refs, offset=off)
    off += n_refs * 8
    pay = np.frombuffer(payload, dtype=np.float32, count=n_pay, offset=off)
    return InferRequest(
        static_hash=static_hash,
        client_id=client_id,
        req_id=req_id,
        dyn_obs=dyn_obs,
        refs=refs,
        pay=pay,
    )


def encode_infer_response(resp: InferResponse) -> bytes:
    """Serialize InferResponse 含 outer length prefix。 mirror Go EncodeInferResponse。"""
    if resp.status == INFER_STATUS_OK:
        if resp.logits is None:
            logits_bytes = b''
            n_logits = 0
        else:
            n_logits = len(resp.logits)
            if n_logits > 0xFFFF:
                raise ValueError(f'logits len {n_logits} > u16 max')
            logits_bytes = resp.logits.astype(np.float32, copy=False).tobytes()
        payload_len = RESPONSE_HEADER_SIZE + len(logits_bytes)
        return b''.join(
            [
                struct.pack('<I', payload_len),
                struct.pack('<BH', INFER_STATUS_OK, n_logits),
                logits_bytes,
            ]
        )
    # err path
    err_bytes = resp.err_msg.encode('utf-8')
    if len(err_bytes) > 0xFFFF:
        raise ValueError(f'err_msg len {len(err_bytes)} > u16 max')
    payload_len = RESPONSE_HEADER_SIZE + len(err_bytes)
    return b''.join(
        [
            struct.pack('<I', payload_len),
            struct.pack('<BH', INFER_STATUS_ERR, len(err_bytes)),
            err_bytes,
        ]
    )


def decode_infer_response(payload: bytes) -> InferResponse:
    """Deserialize InferResponse payload(不含 outer length prefix)。"""
    if len(payload) < RESPONSE_HEADER_SIZE:
        raise ValueError(f'response payload {len(payload)} byte < header {RESPONSE_HEADER_SIZE}')
    status, n = struct.unpack_from('<BH', payload, 0)
    if status == INFER_STATUS_OK:
        expected_len = RESPONSE_HEADER_SIZE + n * 4
        if len(payload) != expected_len:
            raise ValueError(f'ok response len {len(payload)} != expected {expected_len} (n_logits={n})')
        logits = (
            np.frombuffer(payload, dtype=np.float32, count=n, offset=RESPONSE_HEADER_SIZE)
            if n > 0
            else np.zeros(0, dtype=np.float32)
        )
        return InferResponse(status=INFER_STATUS_OK, logits=logits)
    if status == INFER_STATUS_ERR:
        expected_len = RESPONSE_HEADER_SIZE + n
        if len(payload) != expected_len:
            raise ValueError(f'err response len {len(payload)} != expected {expected_len} (n_msg={n})')
        return InferResponse(
            status=INFER_STATUS_ERR,
            err_msg=bytes(payload[RESPONSE_HEADER_SIZE : RESPONSE_HEADER_SIZE + n]).decode('utf-8'),
        )
    raise ValueError(f'unknown response status {status}')


def read_length_prefixed(reader) -> bytes:
    """Read [u32 len_le][payload bytes] one message from a reader(socket / BytesIO 等
    支持 ``read(n) -> bytes`` 的对象)。 len 超 MAX_MESSAGE_BYTES → fail loud(防 malformed
    length DoS)。
    """
    len_buf = _read_exact(reader, 4)
    (n,) = struct.unpack('<I', len_buf)
    if n > MAX_MESSAGE_BYTES:
        raise ValueError(f'message len {n} exceeds cap {MAX_MESSAGE_BYTES}')
    return _read_exact(reader, n)


def _read_exact(reader, n: int) -> bytes:
    """Read exactly ``n`` bytes from ``reader``。 raise on short read(防 TCP coalescing
    切分)。"""
    buf = bytearray()
    while len(buf) < n:
        chunk = reader.read(n - len(buf))
        if not chunk:
            raise EOFError(f'short read: got {len(buf)} byte, need {n}')
        buf.extend(chunk)
    return bytes(buf)
