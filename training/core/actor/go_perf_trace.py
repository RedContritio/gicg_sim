"""Go-side perf trace flush — Python ctypes 读 libgicg_actor 的 span aggregator。

mirror Go side gicg_actor/perf_trace.go 的 binary wire format,drain ring buffer
返 list[dict] (per window),与 Python ``training/core/perf/trace.py`` 输出 schema
同 (便于复用同一 jsonl flush + analysis 工具)。

用途:audit Go-actor 端 wall 拆分 (minimax / DeepCopy / inference RPC / Push)。
启用 (post 2026-05-23 cfg-driven):cfg ``[debug] go_perf_trace = true`` →
``tools.runs._train.dispatch`` 调 :func:`set_go_perf_trace_enabled` (capi
gicg_actor_set_perf_trace_enabled) 同步给 Go atomic.Bool。 lib load 后 / 起
pool 前调即可 (无 init-time gate)。 旧 env var ``GICG_GO_PERF_TRACE`` 已废。

Wire format (binary little-endian,与 Go side PerfTraceFlush 对账):

    u32 n_windows
    per window:
      u64 ts_unix_ms
      u32 n_stages
      per stage:
        u16 name_len, name_bytes (utf-8), u32 n, u64 sum_ns, u64 max_ns
"""

from __future__ import annotations

import ctypes
import struct
from typing import Any

from training.core.actor.go_backend import _find_lib

_LIB: ctypes.CDLL | None = None
_DEFAULT_BUF_SIZE = 1 << 20  # 1 MB — 64 windows × ~40 byte/bucket × hundreds bucket 充足


def _load() -> ctypes.CDLL:
    """Lazy-load + bind perf trace ctypes signatures。 缓存 handle。"""
    global _LIB
    if _LIB is None:
        lib = ctypes.CDLL(str(_find_lib()))
        lib.gicg_actor_perf_trace_flush.restype = ctypes.c_int
        lib.gicg_actor_perf_trace_flush.argtypes = [ctypes.c_char_p, ctypes.c_uint32]
        lib.gicg_actor_perf_trace_enabled.restype = ctypes.c_int
        lib.gicg_actor_perf_trace_enabled.argtypes = []
        lib.gicg_actor_set_perf_trace_enabled.restype = ctypes.c_int
        lib.gicg_actor_set_perf_trace_enabled.argtypes = [ctypes.c_int]
        _LIB = lib
    return _LIB


def go_perf_trace_enabled() -> bool:
    """是否 enabled (Go atomic.Bool;cfg-driven 由 set_go_perf_trace_enabled 启)。
    disabled 时 flush 返 []。"""
    return int(_load().gicg_actor_perf_trace_enabled()) == 1


def set_go_perf_trace_enabled(enabled: bool) -> None:
    """cfg-driven enable/disable (post 2026-05-23 旧 GICG_GO_PERF_TRACE env var
    砍后唯一启用路径)。 ``tools.runs._train.dispatch`` 按 cfg.debug.go_perf_trace
    调一次,lib load 后 / 起 pool 前生效即可。 idempotent — 多次 set 反映最新 state。"""
    _load().gicg_actor_set_perf_trace_enabled(ctypes.c_int(1 if enabled else 0))


def flush_go_perf_spans(buf_size: int = _DEFAULT_BUF_SIZE) -> list[dict[str, Any]]:
    """Drain Go side perf trace ring buffer。 返 windows 列表,每 window =
    ``{ts_unix: float, stages: {name: {n, sum_ms, max_ms}}}``。

    disabled / 无数据 → 返 ``[]``。 buf 不够大 → raise (caller 应 retry with
    larger buf_size,但 Go side 在该返码下已 drain ring,数据丢失)。

    单位:Go 内部 ns,Python 转 ms (float, /1e6) 与 trace.py mean_ms 字段对齐。
    """
    lib = _load()
    buf = ctypes.create_string_buffer(buf_size)
    n = int(lib.gicg_actor_perf_trace_flush(buf, ctypes.c_uint32(buf_size)))
    if n == 0:
        return []
    if n < 0:
        raise RuntimeError(f'flush_go_perf_spans: buffer too small, need {-n} bytes (passed {buf_size})')
    return _decode_windows(buf.raw[:n])


def _decode_windows(blob: bytes) -> list[dict[str, Any]]:
    """Binary wire → list[dict]。 失败 raise (协议漂移立即可见)。"""
    out: list[dict[str, Any]] = []
    off = 0
    (n_windows,) = struct.unpack_from('<I', blob, off)
    off += 4
    for _ in range(n_windows):
        (ts_unix_ms, n_stages) = struct.unpack_from('<QI', blob, off)
        off += 12
        stages: dict[str, dict[str, Any]] = {}
        for _s in range(n_stages):
            (name_len,) = struct.unpack_from('<H', blob, off)
            off += 2
            name = blob[off : off + name_len].decode('utf-8')
            off += name_len
            (n, sum_ns, max_ns) = struct.unpack_from('<IQQ', blob, off)
            off += 20
            stages[name] = {
                'n': int(n),
                'sum_ms': round(sum_ns / 1e6, 4),
                'max_ms': round(max_ns / 1e6, 4),
            }
        out.append({'ts_unix': ts_unix_ms / 1000.0, 'stages': stages})
    return out
