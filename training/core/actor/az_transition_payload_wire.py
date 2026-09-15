"""AZ paradigm transition payload codec。

AZ paradigm-specific payload schema(mirror Go AzTransitionHeader)。
跟 DMC 同模式 + 加 root_value (MCTS bootstrap target) + visits (action prob dist)。
改字段时必须 bump AZ_PAYLOAD_VER + 同步 Go AzPayloadVer (lock-step)。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Paradigm-specific payload schema 版本号 — 每次改对应 _AZ_PAYLOAD_FMT 字段顺序 /
# 类型 / 增删都必须 bump。 与 outer WIRE_VERSION 独立(后者管 envelope schema,本字段
# 管 paradigm payload schema)。 Go 端 AzPayloadVer 须 lock-step,decode 时 mismatch
# fail-loud。
#
# The explicit version also catches same-length field-layout changes that a
# payload-size check cannot detect.
AZ_PAYLOAD_VER = 1

_AZ_PAYLOAD_FMT = '<B I I i i I I I I I I 16s'
_AZ_PAYLOAD_FIELDS = (
    'payload_ver',
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
class AzTransitionPayload:
    """AZ paradigm-specific payload after decoding ``Transition.payload``。

    ``visits`` is the normalized MCTS root distribution used as the policy
    target. ``root_value`` is the root value estimate stored with the sample.
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
        'payload_ver': AZ_PAYLOAD_VER,
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
    if header['payload_ver'] != AZ_PAYLOAD_VER:
        raise ValueError(
            f'AZ payload version mismatch: got {header["payload_ver"]}, want {AZ_PAYLOAD_VER} '
            '(Go AzPayloadVer 与 Python AZ_PAYLOAD_VER 不同步)'
        )
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
            # `.copy()` — 同 DMC,view 钉源 blob,拷出后 blob 立即可释放。
            arrays[name] = np.frombuffer(blob, dtype=dtype, count=n, offset=off).copy()
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
