"""Python side wire format for Go actor → Python trainer transition push socket。

Mirror Go ``gicg_actor/transition_wire.go`` 1:1。 separate from inference wire(那走
``inference_server_socket_wire.py``)。

Outer envelope(paradigm-agnostic):

    [u16 ver][u32 client_id][u32 episode_id][u32 step][u8 done][u8 _reserved]
    [u32 n_payload_bytes] | payload_bytes  (paradigm-specific opaque blob)

Outer frame:``[u32 len_le][payload bytes]``。

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

WIRE_VERSION = 1
TRANSITION_HEADER_SIZE = 2 + 4 + 4 + 4 + 1 + 1 + 4  # 20 bytes fixed
MAX_TRANSITION_PAYLOAD = 16 * 1024 * 1024  # 16 MB cap, same as InferRequest


@dataclass
class Transition:
    """Envelope decoded from socket — paradigm-agnostic header + opaque payload bytes。

    payload 是 paradigm-specific raw bytes;DMC layout 见 ``decode_dmc_payload``。
    """

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
    payload_len = TRANSITION_HEADER_SIZE + len(t.payload)
    parts = [
        struct.pack('<I', payload_len),
        struct.pack('<H', WIRE_VERSION),
        struct.pack('<III', t.client_id, t.episode_id, t.step),
        struct.pack('<BB', 1 if t.done else 0, 0),
        struct.pack('<I', len(t.payload)),
        t.payload,
    ]
    return b''.join(parts)


def decode_transition(payload: bytes) -> Transition:
    """Deserialize Transition envelope payload(不含 outer length prefix)。
    mirror Go DecodeTransition。
    """
    if len(payload) < TRANSITION_HEADER_SIZE:
        raise ValueError(f'transition payload {len(payload)} < header {TRANSITION_HEADER_SIZE}')
    (ver,) = struct.unpack_from('<H', payload, 0)
    if ver != WIRE_VERSION:
        raise ValueError(f'transition wire version mismatch: got {ver}, want {WIRE_VERSION}')
    client_id, episode_id, step = struct.unpack_from('<III', payload, 2)
    done_byte, _reserved = struct.unpack_from('<BB', payload, 14)
    (n_payload,) = struct.unpack_from('<I', payload, 16)
    expected = TRANSITION_HEADER_SIZE + n_payload
    if len(payload) != expected:
        raise ValueError(f'transition payload len {len(payload)} != expected {expected} (n={n_payload})')
    body = bytes(payload[TRANSITION_HEADER_SIZE:])
    return Transition(
        client_id=client_id,
        episode_id=episode_id,
        step=step,
        done=done_byte != 0,
        payload=body,
    )


def decode_dmc_payload(blob: bytes, *, dyn_obs_len: Optional[int] = None) -> DmcTransitionPayload:
    """Decode DMC paradigm payload bytes(``Transition.payload``)。

    Layout:[u32 chosen][u32 step][i32 reward_x1m] | dyn_obs (f32 ×N)

    ``dyn_obs_len`` 可选:caller 已知 dyn_obs 长度时强校 — production 路径里
    InferenceServer 在第一次 inference request 时知 n_dyn(同 episode 跨 step
    不变),caller 可用之 verify。 None 时按 trailing bytes / 4 推断。
    """
    if len(blob) < 12:
        raise ValueError(f'DMC payload {len(blob)} byte < header 12')
    chosen, step_in_ep = struct.unpack_from('<II', blob, 0)
    (reward_x1m,) = struct.unpack_from('<i', blob, 8)
    reward = reward_x1m / 1e6
    dyn_bytes = blob[12:]
    if len(dyn_bytes) % 4 != 0:
        raise ValueError(f'DMC payload dyn_obs bytes {len(dyn_bytes)} not multiple of 4')
    dyn_obs = np.frombuffer(dyn_bytes, dtype=np.float32)
    if dyn_obs_len is not None and len(dyn_obs) != dyn_obs_len:
        raise ValueError(f'DMC dyn_obs len {len(dyn_obs)} != expected {dyn_obs_len}')
    return DmcTransitionPayload(
        chosen_action=chosen,
        step_in_episode=step_in_ep,
        reward=reward,
        dyn_obs=dyn_obs,
    )


def read_length_prefixed(reader) -> bytes:
    """Read [u32 length_le] then ``length`` byte payload。 mirror inference wire helper。

    reader.read(n) 返 b'' 表 EOF → raise EOFError(caller per-conn handler 静默退出)。
    """
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
