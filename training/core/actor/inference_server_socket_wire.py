"""Python side wire format for Go actor ↔ Python InferenceServer socket protocol。

Mirror Go ``gicg_actor/wire_format.go`` 1:1 — same little-endian byte layout,无 pickle
overhead,zero-copy via ``np.frombuffer`` view。 schema 详 design.md D5 + 实测 < 1μs RTT
(IPC research agent 2026-05-21 验证)。

Schema is declarative — header layout described by a single ``struct`` format string,
variable-length array sections described by a list of (name, dtype, count_field) tuples。
Adding a new field = 1 line in ``_HEADER_FMT`` / ``_HEADER_FIELDS`` (固定字段) 或一行
``_ARRAY_SPECS`` (可变长 array),encode/decode 自动 follow。 同样 Go 端的 fixed-size
struct + binary.Write 模式。

Wire format(inference request,v2):

    header   = struct.pack(_HEADER_FMT, ver, static_hash, client_id, req_id,
                            n_dyn, n_refs, n_pay, n_static)
    payload  = header || dyn_obs (f32 ×N) || refs (i64 ×N) || pay (f32 ×N) || static (i32 ×N)
    outer    = [u32 len_le] || payload

n_static_i32 = 0 表示 "本 request 不带 static_obs"(server 走 hash cache);> 0 时
携带 raw int32 数组,server 端 cache by hash,后续 skip。

Wire format(inference response):

    [u8 status (0=ok, 1=err)][u16 n]
    | logits (n × 4 bytes)   // status=0
    | err_msg bytes          // status=1
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Optional

import numpy as np


def _empty_int32() -> np.ndarray:
    return np.zeros(0, dtype=np.int32)


# ─── Schema 常量 ─────────────────────────────────────────────────────────
WIRE_VERSION = 3  # 跟 transition wire 同步 bump(Go WireVersion 跨两 wire)。inference
# layout 未改,但版本 lock-step;详 transition_sink_wire.py。
STATIC_HASH_SIZE = 16
MAX_MESSAGE_BYTES = 16 * 1024 * 1024
INFER_STATUS_OK = 0
INFER_STATUS_ERR = 1

# Header 固定字段:struct 格式 + 字段名序列。 加字段在两处同步加一行即可。
# n_dyn/n_refs/n_pay/n_static 走 u32 — static_obs ~293K int32 超 u16,统一 u32 减
# mixed schema burden(详 Go InferRequestHeader 注释)。
_HEADER_FMT = '<H 16s I I I I I I'
_HEADER_FIELDS = ('ver', 'static_hash', 'client_id', 'req_id', 'n_dyn', 'n_refs', 'n_pay', 'n_static')
HEADER_SIZE = struct.calcsize(_HEADER_FMT)

# Variable-length array sections following header (顺序固定 = 字节序)。
# 每条:(struct 字段名, numpy dtype, header 计数字段名)。 加 array 在此加一行即可。
_ARRAY_SPECS: tuple[tuple[str, np.dtype, str], ...] = (
    ('dyn_obs', np.dtype(np.float32), 'n_dyn'),
    ('refs', np.dtype(np.int64), 'n_refs'),
    ('pay', np.dtype(np.float32), 'n_pay'),
    ('static', np.dtype(np.int32), 'n_static'),
)

# Response 同样模式 — OK 路径 body = logits[n_logits] f32 + value[n_value] f32;
# Err 路径 body = err_msg bytes(n_logits = err byte length,n_value=0)。
# n_value 通常 0(DMC) 或 1(AZ/PPO 单 scalar V(s))。 u32 统一防 future 扩展。
_RESP_HEADER_FMT = '<B I I'
_RESP_HEADER_FIELDS = ('status', 'n_logits', 'n_value')
RESPONSE_HEADER_SIZE = struct.calcsize(_RESP_HEADER_FMT)


@dataclass
class InferRequest:
    """Decoded request from Go actor。 dyn_obs/refs/pay/static 是 numpy zero-copy view。

    static 可空(len=0)— actor 标记 "本 request 不带 static_obs"(server 走 cache by
    static_hash);非空时 server 端 cache by hash + decode 后保留 decoded result。
    """

    static_hash: bytes
    client_id: int
    req_id: int
    dyn_obs: np.ndarray  # float32 shape (n_dyn,)
    refs: np.ndarray  # int64 shape (n_refs,)
    pay: np.ndarray  # float32 shape (n_pay,)
    # static 默认空 — 调用方未传时等价于 "server 走 cache by static_hash"。
    static: np.ndarray = field(default_factory=_empty_int32)


@dataclass
class InferResponse:
    status: int
    logits: Optional[np.ndarray] = None  # float32 shape (n_logits,) when status=OK
    value: Optional[np.ndarray] = None  # float32 shape (n_value,);n_value=0 DMC / 1 AZ-PPO
    err_msg: str = ''


def encode_infer_request(req: InferRequest) -> bytes:
    """Serialize InferRequest 含 outer length prefix。 mirror Go EncodeInferRequest。"""
    if len(req.static_hash) != STATIC_HASH_SIZE:
        raise ValueError(f'static_hash must be {STATIC_HASH_SIZE} bytes, got {len(req.static_hash)}')

    arrays_data = {}
    counts = {}
    for name, dtype, count_field in _ARRAY_SPECS:
        arr = getattr(req, name)
        arr = np.ascontiguousarray(arr, dtype=dtype)
        if len(arr) > 0xFFFFFFFF:
            raise ValueError(f'{name} len {len(arr)} > u32 max')
        arrays_data[name] = arr.tobytes() if len(arr) > 0 else b''
        counts[count_field] = len(arr)

    header_values = {
        'ver': WIRE_VERSION,
        'static_hash': req.static_hash,
        'client_id': req.client_id,
        'req_id': req.req_id,
        **counts,
    }
    header = struct.pack(_HEADER_FMT, *(header_values[f] for f in _HEADER_FIELDS))

    payload_len = len(header) + sum(len(b) for b in arrays_data.values())
    parts = [struct.pack('<I', payload_len), header]
    parts.extend(arrays_data[name] for name, _, _ in _ARRAY_SPECS)
    return b''.join(parts)


def decode_infer_request(payload: bytes) -> InferRequest:
    """Deserialize InferRequest payload (不含 outer length prefix)。 mirror Go
    DecodeInferRequest。 numpy arrays are read-only zero-copy views into payload。
    """
    if len(payload) < HEADER_SIZE:
        raise ValueError(f'payload {len(payload)} byte < header {HEADER_SIZE}')
    header = dict(zip(_HEADER_FIELDS, struct.unpack_from(_HEADER_FMT, payload, 0)))
    if header['ver'] != WIRE_VERSION:
        raise ValueError(f'wire version mismatch: got {header["ver"]}, want {WIRE_VERSION}')

    expected_len = HEADER_SIZE
    for name, dtype, count_field in _ARRAY_SPECS:
        expected_len += header[count_field] * dtype.itemsize
    if len(payload) != expected_len:
        diagnostics = ' '.join(f'{cf}={header[cf]}' for _, _, cf in _ARRAY_SPECS)
        raise ValueError(f'payload len {len(payload)} != expected {expected_len} ({diagnostics})')

    arrays = {}
    off = HEADER_SIZE
    for name, dtype, count_field in _ARRAY_SPECS:
        n = header[count_field]
        if n > 0:
            arrays[name] = np.frombuffer(payload, dtype=dtype, count=n, offset=off)
        else:
            arrays[name] = np.zeros(0, dtype=dtype)
        off += n * dtype.itemsize

    return InferRequest(
        static_hash=header['static_hash'],
        client_id=header['client_id'],
        req_id=header['req_id'],
        **arrays,
    )


def encode_infer_response(resp: InferResponse) -> bytes:
    """Serialize InferResponse 含 outer length prefix。 mirror Go EncodeInferResponse。

    OK 路径:body = logits[n_logits] f32 + value[n_value] f32。 n_value=0 (DMC) 或
    1(AZ/PPO scalar V(s))。 Err 路径:body = err_msg bytes,n_logits = byte length。
    """
    if resp.status == INFER_STATUS_OK:
        logits = resp.logits if resp.logits is not None else np.zeros(0, dtype=np.float32)
        logits = np.ascontiguousarray(logits, dtype=np.float32)
        value = resp.value if resp.value is not None else np.zeros(0, dtype=np.float32)
        value = np.ascontiguousarray(value, dtype=np.float32)
        if len(logits) > 0xFFFFFFFF or len(value) > 0xFFFFFFFF:
            raise ValueError(f'logits/value len > u32 max')
        body = logits.tobytes() + value.tobytes()
        header = struct.pack(_RESP_HEADER_FMT, INFER_STATUS_OK, len(logits), len(value))
    elif resp.status == INFER_STATUS_ERR:
        body = resp.err_msg.encode('utf-8')
        if len(body) > 0xFFFFFFFF:
            raise ValueError(f'err_msg len {len(body)} > u32 max')
        header = struct.pack(_RESP_HEADER_FMT, INFER_STATUS_ERR, len(body), 0)
    else:
        raise ValueError(f'unknown response status {resp.status}')

    payload_len = len(header) + len(body)
    return b''.join([struct.pack('<I', payload_len), header, body])


def decode_infer_response(payload: bytes) -> InferResponse:
    """Deserialize InferResponse payload(不含 outer length prefix)。"""
    if len(payload) < RESPONSE_HEADER_SIZE:
        raise ValueError(f'response payload {len(payload)} byte < header {RESPONSE_HEADER_SIZE}')
    status, n_logits, n_value = struct.unpack_from(_RESP_HEADER_FMT, payload, 0)
    if status == INFER_STATUS_OK:
        expected_len = RESPONSE_HEADER_SIZE + n_logits * 4 + n_value * 4
        if len(payload) != expected_len:
            raise ValueError(
                f'ok response len {len(payload)} != expected {expected_len} (n_logits={n_logits} n_value={n_value})'
            )
        off = RESPONSE_HEADER_SIZE
        logits = (
            np.frombuffer(payload, dtype=np.float32, count=n_logits, offset=off)
            if n_logits > 0
            else np.zeros(0, dtype=np.float32)
        )
        off += n_logits * 4
        value = (
            np.frombuffer(payload, dtype=np.float32, count=n_value, offset=off)
            if n_value > 0
            else np.zeros(0, dtype=np.float32)
        )
        return InferResponse(status=INFER_STATUS_OK, logits=logits, value=value)
    if status == INFER_STATUS_ERR:
        expected_len = RESPONSE_HEADER_SIZE + n_logits
        if len(payload) != expected_len:
            raise ValueError(f'err response len {len(payload)} != expected {expected_len} (n_msg={n_logits})')
        return InferResponse(
            status=INFER_STATUS_ERR,
            err_msg=bytes(payload[RESPONSE_HEADER_SIZE : RESPONSE_HEADER_SIZE + n_logits]).decode('utf-8'),
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
