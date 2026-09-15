"""PPO paradigm transition payload codec。

PPO paradigm-specific payload schema(mirror Go PpoTransitionHeader)。
跟 DMC 同 + 加 log_prob_x1m + value_x1m(GAE bootstrap target)。
改字段时必须 bump PPO_PAYLOAD_VER + 同步 Go PpoPayloadVer (lock-step)。
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Paradigm-specific payload schema 版本号 — 每次改对应 _PPO_PAYLOAD_FMT 字段顺序 /
# 类型 / 增删都必须 bump。 与 outer WIRE_VERSION 独立(后者管 envelope schema,本字段
# 管 paradigm payload schema)。 Go 端 PpoPayloadVer 须 lock-step,decode 时 mismatch
# fail-loud。
#
# The explicit version also catches same-length field-layout changes that a
# payload-size check cannot detect.
PPO_PAYLOAD_VER = 1

_PPO_PAYLOAD_FMT = '<B I I i i i I I I I I 16s'
_PPO_PAYLOAD_FIELDS = (
    'payload_ver',
    'chosen_action',
    'step_in_episode',
    'reward_x1m',
    'log_prob_x1m',
    'value_x1m',
    'n_legal',
    'n_dyn',
    'n_refs',
    'n_pay',
    'n_static',
    'static_hash',
)
_PPO_PAYLOAD_HEADER_SIZE = struct.calcsize(_PPO_PAYLOAD_FMT)

_PPO_PAYLOAD_ARRAYS: tuple[tuple[str, np.dtype, str], ...] = (
    ('dyn_obs', np.dtype(np.float32), 'n_dyn'),
    ('refs', np.dtype(np.int64), 'n_refs'),
    ('pay', np.dtype(np.float32), 'n_pay'),
    ('static', np.dtype(np.int32), 'n_static'),
)


@dataclass
class PpoTransitionPayload:
    """PPO paradigm-specific payload after decoding ``Transition.payload``。

    ``log_prob`` is the old-policy likelihood of the sampled action.
    ``value`` is ``V(s)`` before the environment step and feeds GAE.
    """

    chosen_action: int
    step_in_episode: int
    reward: float
    log_prob: float
    value: float
    n_legal: int
    static_hash: bytes
    dyn_obs: np.ndarray
    refs: np.ndarray
    pay: np.ndarray
    static: np.ndarray


def encode_ppo_payload(
    *,
    chosen_action: int,
    step_in_episode: int,
    reward: float,
    log_prob: float,
    value: float,
    n_legal: int,
    static_hash: bytes,
    dyn_obs: np.ndarray,
    refs: np.ndarray,
    pay: np.ndarray,
    static: Optional[np.ndarray] = None,
) -> bytes:
    """Encode PPO paradigm payload bytes(mirror Go EncodePpoTransitionPayload)。 Test
    用 mirror。"""
    if len(static_hash) != 16:
        raise ValueError(f'static_hash must be 16 bytes, got {len(static_hash)}')
    static_arr = static if static is not None else np.zeros(0, dtype=np.int32)
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
        'payload_ver': PPO_PAYLOAD_VER,
        'chosen_action': chosen_action,
        'step_in_episode': step_in_episode,
        'reward_x1m': int(reward * 1e6),
        'log_prob_x1m': int(log_prob * 1e6),
        'value_x1m': int(value * 1e6),
        'n_legal': n_legal,
        'static_hash': static_hash,
        **counts,
    }
    header = struct.pack(_PPO_PAYLOAD_FMT, *(header_values[f] for f in _PPO_PAYLOAD_FIELDS))
    parts = [header]
    for name, _, _ in _PPO_PAYLOAD_ARRAYS:
        arr = arrays[name]
        if arr.size > 0:
            parts.append(arr.tobytes())
    return b''.join(parts)


def decode_ppo_payload(blob: bytes) -> PpoTransitionPayload:
    """Decode PPO paradigm payload bytes(``Transition.payload``)。"""
    if len(blob) < _PPO_PAYLOAD_HEADER_SIZE:
        raise ValueError(f'PPO payload {len(blob)} byte < header {_PPO_PAYLOAD_HEADER_SIZE}')
    header = dict(zip(_PPO_PAYLOAD_FIELDS, struct.unpack_from(_PPO_PAYLOAD_FMT, blob, 0)))
    if header['payload_ver'] != PPO_PAYLOAD_VER:
        raise ValueError(
            f'PPO payload version mismatch: got {header["payload_ver"]}, want {PPO_PAYLOAD_VER} '
            '(Go PpoPayloadVer 与 Python PPO_PAYLOAD_VER 不同步)'
        )
    expected_len = _PPO_PAYLOAD_HEADER_SIZE
    for _, dtype, count_field in _PPO_PAYLOAD_ARRAYS:
        expected_len += header[count_field] * dtype.itemsize
    if len(blob) != expected_len:
        diagnostics = ' '.join(f'{cf}={header[cf]}' for _, _, cf in _PPO_PAYLOAD_ARRAYS)
        raise ValueError(f'PPO payload len {len(blob)} != expected {expected_len} ({diagnostics})')

    arrays = {}
    off = _PPO_PAYLOAD_HEADER_SIZE
    for name, dtype, count_field in _PPO_PAYLOAD_ARRAYS:
        n = header[count_field]
        if n > 0:
            # `.copy()` — 同 DMC,view 钉源 blob,拷出后 blob 立即可释放。
            arrays[name] = np.frombuffer(blob, dtype=dtype, count=n, offset=off).copy()
        else:
            arrays[name] = np.zeros(0, dtype=dtype)
        off += n * dtype.itemsize

    return PpoTransitionPayload(
        chosen_action=header['chosen_action'],
        step_in_episode=header['step_in_episode'],
        reward=header['reward_x1m'] / 1e6,
        log_prob=header['log_prob_x1m'] / 1e6,
        value=header['value_x1m'] / 1e6,
        n_legal=header['n_legal'],
        static_hash=header['static_hash'],
        **arrays,
    )
