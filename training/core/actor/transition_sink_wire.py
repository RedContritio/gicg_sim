"""Python transition wire format for Go actors and the Python trainer (envelope).

The layout mirrors ``gicg_actor/transition_wire.go`` and is independent
from ``inference_server_socket_wire.py``. Fixed headers use declarative
format/field tables; the paradigm-specific payload blob the frames carry
is opaque here and is handled by the sibling payload modules
(``dmc_transition_payload_wire`` / ``az_transition_payload_wire`` /
``ppo_transition_payload_wire``).

Outer envelope(paradigm-agnostic):

    header  = struct.pack(_HEADER_FMT, ver, client_id, episode_id, step, done, reserved, n_payload)
    payload = header || payload_bytes  (paradigm-specific opaque blob)
    outer   = [u32 len_le] || payload

``KIND_EPISODE_BATCH`` frames put ``_EPISODE_BATCH_HEADER_FMT`` right behind
the same outer length prefix, followed by N per-transition records.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass

# ─── Schema 常量 ─────────────────────────────────────────────────────────
# This stays in lockstep with the inference protocol's Go WireVersion.
WIRE_VERSION = 3
# DMC/PPO reference and payment arrays contain ``n_legal`` rows. Sampling
# code pads them to the configured action capacity during collation.
MAX_TRANSITION_PAYLOAD = 16 * 1024 * 1024

# Kind byte — 区分 per-transition frame 和 episode batch frame。
KIND_PER_TRANS = 0  # 原 per-transition frame(backward compat)
KIND_EPISODE_BATCH = 1  # F1 episode batch frame

# Header 固定字段:加字段在两处加一行即可。
# Kind 字段在 Done 之前(offset 14),与 EpisodeBatchHeader.Kind 同 offset,listener 可靠 peek。
# 顺序:ver, client_id, episode_id, step, kind(offset 14), done(offset 15), n_payload
_HEADER_FMT = '<H I I I B B I'  # ver, client_id, episode_id, step, kind, done, n_payload
_HEADER_FIELDS = ('ver', 'client_id', 'episode_id', 'step', 'kind', 'done', 'n_payload')
TRANSITION_HEADER_SIZE = struct.calcsize(_HEADER_FMT)

# EpisodeBatch header — mirror Go EpisodeBatchHeader。
# 紧接 outer length prefix(4 byte)之后,Kind=1 时 listener 走本 header 路径。
_EPISODE_BATCH_HEADER_FMT = '<H I I I B B'  # ver, client_id, episode_id, n_trans, kind, reserved
_EPISODE_BATCH_HEADER_FIELDS = ('ver', 'client_id', 'episode_id', 'n_trans', 'kind', 'reserved')
EPISODE_BATCH_HEADER_SIZE = struct.calcsize(_EPISODE_BATCH_HEADER_FMT)


@dataclass
class Transition:
    """Paradigm-agnostic envelope with opaque payload bytes."""

    client_id: int
    episode_id: int
    step: int
    done: bool
    payload: bytes


@dataclass
class EpisodeBatch:
    """An entire episode encoded as one ``KIND_EPISODE_BATCH`` frame.

    ``transitions`` contains the step payloads and its final entry carries
    ``done=True``.
    """

    client_id: int
    episode_id: int
    transitions: list['Transition']


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
        'kind': KIND_PER_TRANS,
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


def decode_episode_batch(payload: bytes) -> EpisodeBatch:
    """Deserialize EpisodeBatch frame payload(不含 outer length prefix)。 mirror Go DecodeEpisodeBatch。

    F1 episode-granularity batch frame:payload 紧跟 EpisodeBatchHeader 后接 N 个
    [u32 payload_len][u8 done][u8 reserved][payload_bytes]。
    """
    if len(payload) < EPISODE_BATCH_HEADER_SIZE:
        raise ValueError(f'episode batch payload {len(payload)} < header {EPISODE_BATCH_HEADER_SIZE}')
    header = dict(zip(_EPISODE_BATCH_HEADER_FIELDS, struct.unpack_from(_EPISODE_BATCH_HEADER_FMT, payload, 0)))
    if header['ver'] != WIRE_VERSION:
        raise ValueError(f'episode batch wire version mismatch: got {header["ver"]}, want {WIRE_VERSION}')
    if header['kind'] != KIND_EPISODE_BATCH:
        raise ValueError(f'episode batch kind mismatch: got {header["kind"]}, want {KIND_EPISODE_BATCH}')
    client_id = header['client_id']
    episode_id = header['episode_id']
    n_trans = header['n_trans']

    off = EPISODE_BATCH_HEADER_SIZE
    transitions: list[Transition] = []
    for i in range(n_trans):
        if off + 6 > len(payload):  # 4(len) + 1(done) + 1(reserved)
            raise ValueError(f'episode batch truncated at trans {i}')
        (pay_len,) = struct.unpack_from('<I', payload, off)
        done = payload[off + 4] != 0
        off += 6  # skip len(4) + done(1) + reserved(1)
        if off + pay_len > len(payload):
            raise ValueError(f'episode batch trans {i} payload {pay_len} overruns frame')
        tx_payload = bytes(payload[off : off + pay_len])
        off += pay_len
        transitions.append(
            Transition(
                client_id=client_id,
                episode_id=episode_id,
                step=0,  # Step not encoded at batch level — DMC payload header carries step_in_episode
                done=done,
                payload=tx_payload,
            )
        )
    return EpisodeBatch(client_id=client_id, episode_id=episode_id, transitions=transitions)


def encode_episode_batch(batch: EpisodeBatch) -> bytes:
    """Serialize EpisodeBatch (含 outer length prefix)。 mirror Go EncodeEpisodeBatch。 Test helper。"""
    n_trans = len(batch.transitions)
    if n_trans == 0:
        raise ValueError('encode_episode_batch: empty transitions')
    batch_header = struct.pack(
        _EPISODE_BATCH_HEADER_FMT,
        WIRE_VERSION,
        batch.client_id,
        batch.episode_id,
        n_trans,
        KIND_EPISODE_BATCH,
        0,  # reserved
    )
    parts = [batch_header]
    for tx in batch.transitions:
        # per-trans: [u32 payload_len] || [u8 done] || [u8 reserved] || payload
        parts.append(struct.pack('<I', len(tx.payload)))
        parts.append(struct.pack('BB', 1 if tx.done else 0, 0))  # done, reserved
        parts.append(tx.payload)
    body = b''.join(parts)
    return struct.pack('<I', len(body)) + body


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
