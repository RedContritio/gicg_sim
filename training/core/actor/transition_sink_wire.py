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
WIRE_VERSION = 3  # 跟 inference protocol 同步 bump(Go 单 WireVersion 跨两份 wire)
# v3 (I29 P2 2026-05-23): DMC/PPO transition payload refs/pay 不再 max_actions
# padded,改为 nlegal-sized — buffer per-trans mem 120 KB → ~12 KB (~10x 降)。
# pad-to-cfg.max_actions 推到 sample time(collate_batch)做。
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

# Paradigm-specific payload schema 版本号 — 每次改对应 _XXX_PAYLOAD_FMT 字段顺序 /
# 类型 / 增删都必须 bump。 与 outer WIRE_VERSION 独立(后者管 envelope schema,本字段
# 管 paradigm payload schema)。 Go 端 obs_encoder.go DmcPayloadVer / AzPayloadVer /
# PpoPayloadVer 须 lock-step,decode 时 mismatch fail-loud。
#
# 2026-05-28 audit:expected_len 校验只能 catch 部分 schema drift(改字段类型保持总
# 长度不变时 silent corruption);1-byte version prefix 是 explicit safety net。
DMC_PAYLOAD_VER = 1
AZ_PAYLOAD_VER = 1
PPO_PAYLOAD_VER = 1

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

# AZ paradigm-specific payload schema(mirror Go AzTransitionHeader)。
# 跟 DMC 同模式 + 加 root_value (MCTS bootstrap target) + visits (action prob dist)。
# 改字段时必须 bump AZ_PAYLOAD_VER + 同步 Go AzPayloadVer (lock-step)。
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

# PPO paradigm-specific payload schema(mirror Go PpoTransitionHeader)。
# 跟 DMC 同 + 加 log_prob_x1m + value_x1m(GAE bootstrap target)。
# 改字段时必须 bump PPO_PAYLOAD_VER + 同步 Go PpoPayloadVer (lock-step)。
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
class Transition:
    """Envelope decoded from socket — paradigm-agnostic header + opaque payload bytes。"""

    client_id: int
    episode_id: int
    step: int
    done: bool
    payload: bytes


@dataclass
class EpisodeBatch:
    """Episode batch decoded from socket — F1 episode-granularity push frame。

    Go side encodes entire episode as single wire frame (Kind=1)。 Python listener
    decodes to EpisodeBatch,assembler.ingest_episode 处理整 episode 一次性入 ready。
    transitions list 包含所有 per-step transitions + terminal marker(Done=True 末条)。
    """

    client_id: int
    episode_id: int
    transitions: list['Transition']


@dataclass
class PpoTransitionPayload:
    """PPO paradigm-specific payload after decoding ``Transition.payload``。

    log_prob 是 actor sampling time 计的 chosen action log-likelihood(PPO ratio 计算
    needs π_old / π_new — log_prob 是 π_old 端)。 value 是 network V(s) at pre-step
    state,GAE bootstrap target。
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
            # 存活源 blob 永不 GC(memory `project_i29_go_actor_pool_progress` audit 已记)。
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
