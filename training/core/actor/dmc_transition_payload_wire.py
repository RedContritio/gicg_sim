"""DMC paradigm transition payload codec。

The self-contained DMC payload mirrors
``gicg_actor/dmc/obs_encoder.go EncodeDmcTransitionPayload``:

    header = struct.pack(_DMC_PAYLOAD_FMT, chosen, step_in_ep, reward_x1m, n_legal,
                          n_dyn, n_refs, n_pay, n_static, static_hash)
    body   = dyn_obs (f32 ×N) || refs (i64 ×N) || pay (f32 ×N) || static (i32 ×N)

The first transition in an episode carries the raw int32 static observation;
later transitions identify it by hash. Rewards use signed fixed point at
``1e6`` scale.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Optional

import numpy as np

# Paradigm-specific payload schema 版本号 — 每次改对应 _DMC_PAYLOAD_FMT 字段顺序 /
# 类型 / 增删都必须 bump。 与 outer WIRE_VERSION 独立(后者管 envelope schema,本字段
# 管 paradigm payload schema)。 Go 端 obs_encoder.go DmcPayloadVer 须 lock-step,
# decode 时 mismatch fail-loud。
#
# The explicit version also catches same-length field-layout changes that a
# payload-size check cannot detect.
DMC_PAYLOAD_VER = 1

# DMC paradigm-specific payload schema(mirror Go DmcTransitionHeader)。
# 加字段在 _DMC_PAYLOAD_FMT / _DMC_PAYLOAD_FIELDS 加一行即可 + 必须 bump
# DMC_PAYLOAD_VER + 同步 Go DmcPayloadVer。
# n_legal/n_dyn/n_refs/n_pay/n_static 走 u32(同 InferRequestHeader)— static_obs 实测
# 可达 ~293K int32,u16 65535 silent overflow 历经实测(2026-05-22)。
_DMC_PAYLOAD_FMT = '<B I I i I I I I I 16s'
_DMC_PAYLOAD_FIELDS = (
    'payload_ver',
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


@dataclass
class DmcTransitionPayload:
    """DMC payload decoded from ``Transition.payload``.

    ``static`` may be empty; the collector then resolves ``static_hash`` from
    its episode cache. Decoders copy non-empty arrays out of the wire buffer.
    """

    chosen_action: int
    step_in_episode: int
    reward: float  # decoded from i32 fixed-point / 1e6
    n_legal: int
    static_hash: bytes
    dyn_obs: np.ndarray  # float32 1D
    refs: np.ndarray  # int64 1D (flat; caller reshapes to (n_legal, 3))
    pay: np.ndarray  # float32 1D (flat; caller reshapes to (n_legal, 8))
    static: np.ndarray  # int32 1D,zero-length if cached


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
        'payload_ver': DMC_PAYLOAD_VER,
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
    if header['payload_ver'] != DMC_PAYLOAD_VER:
        raise ValueError(
            f'DMC payload version mismatch: got {header["payload_ver"]}, want {DMC_PAYLOAD_VER} '
            '(Go DmcPayloadVer 与 Python DMC_PAYLOAD_VER 不同步,可能 Go binary 版本不一致)'
        )

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
            # `.copy()` 必须 —— `np.frombuffer` 返 view 钉着源 blob bytes,只要任一 view
            # 存活源 blob 永不 GC。
            # 拷出独立 array 后 blob 立即可释放。 拷贝代价 ~per-trans 100 KB(max_actions
            # padded refs+pay),可承受;view-pin 在 in-flight episode 周期内累积 master
            # mem,远大于此拷贝代价。
            arrays[name] = np.frombuffer(blob, dtype=dtype, count=n, offset=off).copy()
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
