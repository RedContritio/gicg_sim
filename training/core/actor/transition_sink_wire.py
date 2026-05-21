"""Python side wire format for Go actor → Python trainer transition push socket。

Mirror Go ``gicg_actor/transition_wire.go`` 1:1。 separate from inference wire(那走
``inference_server_socket_wire.py``)。

**Declarative schema** — 跟 inference wire 同模式:fixed header 走 struct format string +
calcsize,加字段在 _HEADER_FMT / _HEADER_FIELDS 加一行即可,encode/decode 自动 follow。

Outer envelope(paradigm-agnostic):

    header  = struct.pack(_HEADER_FMT, ver, client_id, episode_id, step, done, reserved, n_payload)
    payload = header || payload_bytes  (paradigm-specific opaque blob)
    outer   = [u32 len_le] || payload

Paradigm-specific payload(DMC minimum,P1.4 ship):mirror Go
``gicg_actor/dmc/obs_encoder.go EncodeMinimalTransitionPayload``:

    [u32 chosen_action_idx][u32 step_in_episode][i32 reward_x1m] | dyn_obs_f32 raw bytes

reward 走 i32 fixed-point(乘 1e6 再 round)以保 cross-lang determinism — float
encode 在 Go side / Python side 可能 nan-handling 不同 bits。
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

# DMC paradigm-specific payload schema(mirror Go EncodeMinimalTransitionPayload)。
_DMC_PAYLOAD_FMT = '<I I i'  # chosen, step_in_ep, reward_x1m
_DMC_PAYLOAD_FIELDS = ('chosen_action', 'step_in_episode', 'reward_x1m')
_DMC_PAYLOAD_HEADER_SIZE = struct.calcsize(_DMC_PAYLOAD_FMT)


@dataclass
class Transition:
    """Envelope decoded from socket — paradigm-agnostic header + opaque payload bytes。"""

    client_id: int
    episode_id: int
    step: int
    done: bool
    payload: bytes


@dataclass
class DmcTransitionPayload:
    """DMC paradigm-specific payload after decoding ``Transition.payload``。

    dyn_obs 是 zero-copy numpy view into the socket payload bytes(read-only)。
    """

    chosen_action: int
    step_in_episode: int
    reward: float  # decoded from i32 fixed-point / 1e6
    dyn_obs: np.ndarray  # float32 1D


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


def decode_dmc_payload(blob: bytes, *, dyn_obs_len: Optional[int] = None) -> DmcTransitionPayload:
    """Decode DMC paradigm payload bytes(``Transition.payload``)。

    Layout 走 ``_DMC_PAYLOAD_FMT`` + 尾部 dyn_obs f32。 加字段在 ``_DMC_PAYLOAD_FMT`` /
    ``_DMC_PAYLOAD_FIELDS`` 加一行 + dataclass 加属性即可。

    ``dyn_obs_len`` 可选:caller 已知 dyn_obs 长度时强校 — production 路径里
    InferenceServer 在第一次 inference request 时知 n_dyn(同 episode 跨 step
    不变),caller 可用之 verify。 None 时按 trailing bytes / 4 推断。
    """
    if len(blob) < _DMC_PAYLOAD_HEADER_SIZE:
        raise ValueError(f'DMC payload {len(blob)} byte < header {_DMC_PAYLOAD_HEADER_SIZE}')
    fields = dict(zip(_DMC_PAYLOAD_FIELDS, struct.unpack_from(_DMC_PAYLOAD_FMT, blob, 0)))
    dyn_bytes = blob[_DMC_PAYLOAD_HEADER_SIZE:]
    if len(dyn_bytes) % 4 != 0:
        raise ValueError(f'DMC payload dyn_obs bytes {len(dyn_bytes)} not multiple of 4')
    dyn_obs = np.frombuffer(dyn_bytes, dtype=np.float32)
    if dyn_obs_len is not None and len(dyn_obs) != dyn_obs_len:
        raise ValueError(f'DMC dyn_obs len {len(dyn_obs)} != expected {dyn_obs_len}')
    return DmcTransitionPayload(
        chosen_action=fields['chosen_action'],
        step_in_episode=fields['step_in_episode'],
        reward=fields['reward_x1m'] / 1e6,
        dyn_obs=dyn_obs,
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
