"""Python side wire format for Go actor → Python trainer transition push socket。

Mirror Go ``gicg_actor/transition_wire.go`` 1:1。 separate from inference wire(那走
``inference_server_socket_wire.py``)。

**Declarative schema** — 跟 inference wire 同模式:fixed header 走 struct format string +
calcsize,加字段在 _HEADER_FMT / _HEADER_FIELDS 加一行即可,encode/decode 自动 follow。

Outer envelope(paradigm-agnostic):

    header  = struct.pack(_HEADER_FMT, ver, client_id, episode_id, step, done, reserved, n_payload)
    payload = header || payload_bytes  (paradigm-specific opaque blob)
    outer   = [u32 len_le] || payload

Paradigm-specific payload(DMC self-contained,P1.4 ship):mirror Go
``gicg_actor/dmc/obs_encoder.go EncodeDmcTransitionPayload``:

    header = struct.pack(_DMC_PAYLOAD_FMT, chosen, step_in_ep, reward_x1m, n_legal,
                          n_dyn, n_refs, n_pay, n_static, static_hash)
    body   = dyn_obs (f32 ×N) || refs (i64 ×N) || pay (f32 ×N) || static (i32 ×N)

每条 transition self-contained — Python collector 不需要查 InfServer cache
就能 reconstruct DmcTransition。 第一 transition per episode 携带 static_obs
raw int32(NStatic > 0),后续 transition NStatic=0,collector 走 cache by
static_hash 解。 reward 走 i32 fixed-point(×1e6)防 cross-lang nan-bits drift。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

# ─── Schema 常量 ─────────────────────────────────────────────────────────
WIRE_VERSION = 2  # 跟 inference protocol 同步 bump(Go 单 WireVersion 跨两份 wire)
MAX_TRANSITION_PAYLOAD = 16 * 1024 * 1024

# Header 固定字段:加字段在两处加一行即可。
_HEADER_FMT = '<H I I I B B I'  # ver, client_id, episode_id, step, done, reserved, n_payload
_HEADER_FIELDS = ('ver', 'client_id', 'episode_id', 'step', 'done', 'reserved', 'n_payload')
TRANSITION_HEADER_SIZE = struct.calcsize(_HEADER_FMT)

# DMC paradigm-specific payload schema(mirror Go DmcTransitionHeader)。
# 加字段在 _DMC_PAYLOAD_FMT / _DMC_PAYLOAD_FIELDS 加一行即可。
# n_legal/n_dyn/n_refs/n_pay/n_static 走 u32(同 InferRequestHeader)— static_obs 实测
# 可达 ~293K int32,u16 65535 silent overflow 历经实测(2026-05-22)。
_DMC_PAYLOAD_FMT = '<I I i I I I I I 16s'
_DMC_PAYLOAD_FIELDS = (
    'chosen_action',
    'step_in_episode',
    'reward_x1m',
    'n_legal',
    'n_dyn',
    'n_refs',
    'n_pay',
    'n_static',
    'static_hash',
)
_DMC_PAYLOAD_HEADER_SIZE = struct.calcsize(_DMC_PAYLOAD_FMT)

# DMC payload 变长 array sections(顺序固定 = 字节序)。 加 array 在此加一行。
_DMC_PAYLOAD_ARRAYS: tuple[tuple[str, np.dtype, str], ...] = (
    ('dyn_obs', np.dtype(np.float32), 'n_dyn'),
    ('refs', np.dtype(np.int64), 'n_refs'),
    ('pay', np.dtype(np.float32), 'n_pay'),
    ('static', np.dtype(np.int32), 'n_static'),
)

# AZ paradigm-specific payload schema(mirror Go AzTransitionHeader)。
# 跟 DMC 同模式 + 加 root_value (MCTS bootstrap target) + visits (action prob dist)。
_AZ_PAYLOAD_FMT = '<I I i i I I I I I I 16s'
_AZ_PAYLOAD_FIELDS = (
    'chosen_action',
    'step_in_episode',
    'reward_x1m',
    'root_value_x1m',
    'n_legal',
    'n_dyn',
    'n_refs',
    'n_pay',
    'n_static',
    'n_visits',
    'static_hash',
)
_AZ_PAYLOAD_HEADER_SIZE = struct.calcsize(_AZ_PAYLOAD_FMT)

_AZ_PAYLOAD_ARRAYS: tuple[tuple[str, np.dtype, str], ...] = (
    ('dyn_obs', np.dtype(np.float32), 'n_dyn'),
    ('refs', np.dtype(np.int64), 'n_refs'),
    ('pay', np.dtype(np.float32), 'n_pay'),
    ('static', np.dtype(np.int32), 'n_static'),
    ('visits', np.dtype(np.float32), 'n_visits'),
)


@dataclass
class Transition:
    """Envelope decoded from socket — paradigm-agnostic header + opaque payload bytes。"""

    client_id: int
    episode_id: int
    step: int
    done: bool
    payload: bytes


@dataclass
class AzTransitionPayload:
    """AZ paradigm-specific payload after decoding ``Transition.payload``。

    visits 是 MCTS root visits distribution(normalized to sum 1 over legal actions),
    用作 policy gradient training target。 root_value 是 network V(s) at root, GAE-
    equivalent bootstrap target。
    """

    chosen_action: int
    step_in_episode: int
    reward: float
    root_value: float
    n_legal: int
    static_hash: bytes
    dyn_obs: np.ndarray
    refs: np.ndarray
    pay: np.ndarray
    static: np.ndarray
    visits: np.ndarray  # float32 normalized prob dist


@dataclass
class DmcTransitionPayload:
    """DMC paradigm-specific payload after decoding ``Transition.payload``。

    Arrays are zero-copy numpy views into the socket payload bytes(read-only)。
    static 可空(len 0)— Python collector 走 cache by static_hash 取上次 episode-第一
    transition 缓存的 static_obs。
    """

    chosen_action: int
    step_in_episode: int
    reward: float  # decoded from i32 fixed-point / 1e6
    n_legal: int
    static_hash: bytes
    dyn_obs: np.ndarray  # float32 1D
    refs: np.ndarray  # int64 1D (flat,reshape (max_actions, 3) by caller)
    pay: np.ndarray  # float32 1D (flat,reshape (max_actions, 8) by caller)
    static: np.ndarray  # int32 1D,zero-length if cached


def encode_transition(t: Transition) -> bytes:
    """Serialize Transition envelope (含 outer length prefix)。 mirror Go EncodeTransition。

    Roundtrip-helper for tests + Python sender mock。 production 不用 — Go side
    encode + Python side decode。
    """
    if len(t.payload) > MAX_TRANSITION_PAYLOAD:
        raise ValueError(f'transition payload {len(t.payload)} > {MAX_TRANSITION_PAYLOAD} byte cap')
    values = {
        'ver': WIRE_VERSION,
        'client_id': t.client_id,
        'episode_id': t.episode_id,
        'step': t.step,
        'done': 1 if t.done else 0,
        'reserved': 0,
        'n_payload': len(t.payload),
    }
    header = struct.pack(_HEADER_FMT, *(values[f] for f in _HEADER_FIELDS))
    payload_len = len(header) + len(t.payload)
    return b''.join([struct.pack('<I', payload_len), header, t.payload])


def decode_transition(payload: bytes) -> Transition:
    """Deserialize Transition envelope payload(不含 outer length prefix)。
    mirror Go DecodeTransition。
    """
    if len(payload) < TRANSITION_HEADER_SIZE:
        raise ValueError(f'transition payload {len(payload)} < header {TRANSITION_HEADER_SIZE}')
    header = dict(zip(_HEADER_FIELDS, struct.unpack_from(_HEADER_FMT, payload, 0)))
    if header['ver'] != WIRE_VERSION:
        raise ValueError(f'transition wire version mismatch: got {header["ver"]}, want {WIRE_VERSION}')
    expected = TRANSITION_HEADER_SIZE + header['n_payload']
    if len(payload) != expected:
        raise ValueError(f'transition payload len {len(payload)} != expected {expected} (n={header["n_payload"]})')
    body = bytes(payload[TRANSITION_HEADER_SIZE:])
    return Transition(
        client_id=header['client_id'],
        episode_id=header['episode_id'],
        step=header['step'],
        done=header['done'] != 0,
        payload=body,
    )


def encode_dmc_payload(
    *,
    chosen_action: int,
    step_in_episode: int,
    reward: float,
    n_legal: int,
    static_hash: bytes,
    dyn_obs: np.ndarray,
    refs: np.ndarray,
    pay: np.ndarray,
    static: Optional[np.ndarray] = None,
) -> bytes:
    """Encode DMC paradigm payload bytes (mirror Go EncodeDmcTransitionPayload)。

    用于 Python self-test roundtrip 验证。 production Go side encode + Python side
    decode — Python 端不 emit transitions。
    """
    static_arr = static if static is not None else np.zeros(0, dtype=np.int32)
    if len(static_hash) != 16:
        raise ValueError(f'static_hash must be 16 bytes, got {len(static_hash)}')

    arrays = {
        'dyn_obs': np.ascontiguousarray(dyn_obs, dtype=np.float32),
        'refs': np.ascontiguousarray(refs, dtype=np.int64),
        'pay': np.ascontiguousarray(pay, dtype=np.float32),
        'static': np.ascontiguousarray(static_arr, dtype=np.int32),
    }
    counts = {
        'n_dyn': len(arrays['dyn_obs']),
        'n_refs': len(arrays['refs']),
        'n_pay': len(arrays['pay']),
        'n_static': len(arrays['static']),
    }
    header_values = {
        'chosen_action': chosen_action,
        'step_in_episode': step_in_episode,
        'reward_x1m': int(reward * 1e6),
        'n_legal': n_legal,
        'static_hash': static_hash,
        **counts,
    }
    header = struct.pack(_DMC_PAYLOAD_FMT, *(header_values[f] for f in _DMC_PAYLOAD_FIELDS))
    parts = [header]
    for name, _, _ in _DMC_PAYLOAD_ARRAYS:
        arr = arrays[name]
        if arr.size > 0:
            parts.append(arr.tobytes())
    return b''.join(parts)


def decode_dmc_payload(blob: bytes, *, dyn_obs_len: Optional[int] = None) -> DmcTransitionPayload:
    """Decode DMC paradigm payload bytes(``Transition.payload``)。

    Layout 走 ``_DMC_PAYLOAD_FMT`` header + ``_DMC_PAYLOAD_ARRAYS`` 顺序变长 sections。
    加字段在两处加一行 + dataclass 加属性即可。

    ``dyn_obs_len`` 可选:caller 已知 dyn_obs 长度时强校 — production 路径里
    InferenceServer 在第一次 inference request 时知 n_dyn(同 episode 跨 step 不变),
    caller 可用之 verify。 None 时按 header.n_dyn 推断(默认信任 wire,该字段独立 verify
    by 整 payload len)。
    """
    if len(blob) < _DMC_PAYLOAD_HEADER_SIZE:
        raise ValueError(f'DMC payload {len(blob)} byte < header {_DMC_PAYLOAD_HEADER_SIZE}')
    header = dict(zip(_DMC_PAYLOAD_FIELDS, struct.unpack_from(_DMC_PAYLOAD_FMT, blob, 0)))

    expected_len = _DMC_PAYLOAD_HEADER_SIZE
    for _, dtype, count_field in _DMC_PAYLOAD_ARRAYS:
        expected_len += header[count_field] * dtype.itemsize
    if len(blob) != expected_len:
        diagnostics = ' '.join(f'{cf}={header[cf]}' for _, _, cf in _DMC_PAYLOAD_ARRAYS)
        raise ValueError(f'DMC payload len {len(blob)} != expected {expected_len} ({diagnostics})')

    if dyn_obs_len is not None and header['n_dyn'] != dyn_obs_len:
        raise ValueError(f'DMC dyn_obs len {header["n_dyn"]} != expected {dyn_obs_len}')

    arrays = {}
    off = _DMC_PAYLOAD_HEADER_SIZE
    for name, dtype, count_field in _DMC_PAYLOAD_ARRAYS:
        n = header[count_field]
        if n > 0:
            arrays[name] = np.frombuffer(blob, dtype=dtype, count=n, offset=off)
        else:
            arrays[name] = np.zeros(0, dtype=dtype)
        off += n * dtype.itemsize

    return DmcTransitionPayload(
        chosen_action=header['chosen_action'],
        step_in_episode=header['step_in_episode'],
        reward=header['reward_x1m'] / 1e6,
        n_legal=header['n_legal'],
        static_hash=header['static_hash'],
        **arrays,
    )


def encode_az_payload(
    *,
    chosen_action: int,
    step_in_episode: int,
    reward: float,
    root_value: float,
    n_legal: int,
    static_hash: bytes,
    dyn_obs: np.ndarray,
    refs: np.ndarray,
    pay: np.ndarray,
    static: Optional[np.ndarray] = None,
    visits: Optional[np.ndarray] = None,
) -> bytes:
    """Encode AZ paradigm payload bytes(mirror Go EncodeAzTransitionPayload)。 Test
    用 mirror — production Go side encode + Python side decode。"""
    if len(static_hash) != 16:
        raise ValueError(f'static_hash must be 16 bytes, got {len(static_hash)}')
    static_arr = static if static is not None else np.zeros(0, dtype=np.int32)
    visits_arr = visits if visits is not None else np.zeros(0, dtype=np.float32)

    arrays = {
        'dyn_obs': np.ascontiguousarray(dyn_obs, dtype=np.float32),
        'refs': np.ascontiguousarray(refs, dtype=np.int64),
        'pay': np.ascontiguousarray(pay, dtype=np.float32),
        'static': np.ascontiguousarray(static_arr, dtype=np.int32),
        'visits': np.ascontiguousarray(visits_arr, dtype=np.float32),
    }
    counts = {
        'n_dyn': len(arrays['dyn_obs']),
        'n_refs': len(arrays['refs']),
        'n_pay': len(arrays['pay']),
        'n_static': len(arrays['static']),
        'n_visits': len(arrays['visits']),
    }
    header_values = {
        'chosen_action': chosen_action,
        'step_in_episode': step_in_episode,
        'reward_x1m': int(reward * 1e6),
        'root_value_x1m': int(root_value * 1e6),
        'n_legal': n_legal,
        'static_hash': static_hash,
        **counts,
    }
    header = struct.pack(_AZ_PAYLOAD_FMT, *(header_values[f] for f in _AZ_PAYLOAD_FIELDS))
    parts = [header]
    for name, _, _ in _AZ_PAYLOAD_ARRAYS:
        arr = arrays[name]
        if arr.size > 0:
            parts.append(arr.tobytes())
    return b''.join(parts)


def decode_az_payload(blob: bytes) -> AzTransitionPayload:
    """Decode AZ paradigm payload bytes(``Transition.payload``)。"""
    if len(blob) < _AZ_PAYLOAD_HEADER_SIZE:
        raise ValueError(f'AZ payload {len(blob)} byte < header {_AZ_PAYLOAD_HEADER_SIZE}')
    header = dict(zip(_AZ_PAYLOAD_FIELDS, struct.unpack_from(_AZ_PAYLOAD_FMT, blob, 0)))
    expected_len = _AZ_PAYLOAD_HEADER_SIZE
    for _, dtype, count_field in _AZ_PAYLOAD_ARRAYS:
        expected_len += header[count_field] * dtype.itemsize
    if len(blob) != expected_len:
        diagnostics = ' '.join(f'{cf}={header[cf]}' for _, _, cf in _AZ_PAYLOAD_ARRAYS)
        raise ValueError(f'AZ payload len {len(blob)} != expected {expected_len} ({diagnostics})')

    arrays = {}
    off = _AZ_PAYLOAD_HEADER_SIZE
    for name, dtype, count_field in _AZ_PAYLOAD_ARRAYS:
        n = header[count_field]
        if n > 0:
            arrays[name] = np.frombuffer(blob, dtype=dtype, count=n, offset=off)
        else:
            arrays[name] = np.zeros(0, dtype=dtype)
        off += n * dtype.itemsize

    return AzTransitionPayload(
        chosen_action=header['chosen_action'],
        step_in_episode=header['step_in_episode'],
        reward=header['reward_x1m'] / 1e6,
        root_value=header['root_value_x1m'] / 1e6,
        n_legal=header['n_legal'],
        static_hash=header['static_hash'],
        **arrays,
    )


def read_length_prefixed(reader) -> bytes:
    """Read [u32 length_le] then ``length`` byte payload。 mirror inference wire helper。"""
    head = _read_exact(reader, 4)
    (length,) = struct.unpack('<I', head)
    if length > MAX_TRANSITION_PAYLOAD:
        raise ValueError(f'transition outer length {length} > {MAX_TRANSITION_PAYLOAD} byte cap')
    return _read_exact(reader, length)


def _read_exact(reader, n: int) -> bytes:
    """Read exactly n bytes,short read → EOFError。"""
    buf = bytearray()
    while len(buf) < n:
        chunk = reader.read(n - len(buf))
        if not chunk:
            raise EOFError(f'short read: got {len(buf)} byte, want {n}')
        buf.extend(chunk)
    return bytes(buf)
