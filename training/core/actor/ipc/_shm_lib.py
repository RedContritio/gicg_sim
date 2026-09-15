"""Native ``libshm`` binding + SHM ring ABI layout.

Loads (building on demand) the C library behind ``CrossLangShmRing`` and
declares the ctypes signatures that match ``gicg_actor/shm/shm_ring.h``.
See ``openspec/changes/archive/i29-go-actor-pool/shminf_design.md`` §D.

Split out of ``ring_shm`` so each module stays within the 300-line source
cap; the public ``CrossLangShmRing`` stays in ``ring_shm``.

Platforms: macOS/Linux use ``shm_unix.c`` and Windows uses ``shm_win.c``.
On-demand Windows builds require GCC. POSIX native calls prepend ``/`` to
the SharedMemory name; Windows passes the name verbatim.
"""

from __future__ import annotations

import ctypes
import struct as _struct
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Layout constants — must match shm_ring.h.
_SHM_RING_HEADER_SIZE = 64
_SHM_SLOT_HEADER_SIZE = 20

_REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent
_SHM_DIR = _REPO_ROOT / 'gicg_actor' / 'shm'

if sys.platform == 'darwin':
    _LIB_FILENAME, _LIB_SRC = 'libshm.dylib', 'shm_unix.c'
elif sys.platform.startswith('linux'):
    _LIB_FILENAME, _LIB_SRC = 'libshm.so', 'shm_unix.c'
elif sys.platform == 'win32':
    _LIB_FILENAME, _LIB_SRC = 'libshm.dll', 'shm_win.c'
else:
    _LIB_FILENAME, _LIB_SRC = None, None  # ctor raises NotImplementedError


def _ring_total_size(capacity: int, slot_payload_max: int) -> int:
    return _SHM_RING_HEADER_SIZE + capacity * (_SHM_SLOT_HEADER_SIZE + slot_payload_max)


class _ShmHandle(ctypes.Structure):
    _fields_ = [('ptr', ctypes.c_void_p), ('size', ctypes.c_int64)]


# lib search path — colocated with shm_*.c + gicg_env/ drop-in (Win has no /tmp).
_SEARCH_PATHS: list[Path] = [
    _SHM_DIR / _LIB_FILENAME if _LIB_FILENAME else Path('/dev/null'),
    _REPO_ROOT / 'gicg_env' / (_LIB_FILENAME or ''),
]


def _build_shm_lib(out_path: Path) -> None:
    """Compile libshm on demand. Win: gcc + -lkernel32 (no fPIC); else: cc + -fPIC.

    Stays on gcc family on Win (matches cgo toolchain) so ABI struct layout
    aligns with Go — MSVC differs on struct padding edge cases.
    """
    if _LIB_FILENAME is None or _LIB_SRC is None:
        raise RuntimeError(f'CrossLangShmRing: unsupported platform {sys.platform}')
    src = _SHM_DIR / _LIB_SRC
    if sys.platform == 'win32':
        cmd = ['gcc', '-shared', '-O2', '-o', str(out_path), str(src), '-I', str(_SHM_DIR), '-lkernel32']
    else:
        cmd = ['cc', '-shared', '-fPIC', '-O2', '-o', str(out_path), str(src), '-I', str(_SHM_DIR)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f'CrossLangShmRing: failed to compile libshm via {cmd[0]}:\n{result.stderr}')


def _find_or_build_lib() -> Path:
    for candidate in _SEARCH_PATHS:
        if candidate.exists():
            return candidate
    out = _SHM_DIR / (_LIB_FILENAME or '')
    _build_shm_lib(out)
    return out


def _load_lib() -> ctypes.CDLL:
    lib = ctypes.CDLL(str(_find_or_build_lib()))
    P = ctypes.POINTER
    u32 = ctypes.c_uint32
    i32 = ctypes.c_int
    i64 = ctypes.c_int64
    vp = ctypes.c_void_p
    cp = ctypes.c_char_p
    ei = P(i32)
    H = _ShmHandle
    lib.shm_create.argtypes = [cp, i64, ei]
    lib.shm_create.restype = H
    lib.shm_attach.argtypes = [cp, i64, ei]
    lib.shm_attach.restype = H
    lib.shm_detach.argtypes = [H]
    lib.shm_detach.restype = None
    lib.shm_unlink_name.argtypes = [cp]
    lib.shm_unlink_name.restype = None
    lib.shm_ring_push.argtypes = [H, u32, u32, vp, u32]
    lib.shm_ring_push.restype = i32
    lib.shm_ring_pop.argtypes = [H, P(u32), P(u32), vp, P(u32), u32]
    lib.shm_ring_pop.restype = i32
    lib.shm_resp_write.argtypes = [H, u32, vp, u32, i32]
    lib.shm_resp_write.restype = i32
    lib.shm_resp_read.argtypes = [H, P(u32), vp, P(u32), u32, i32]
    lib.shm_resp_read.restype = i32
    return lib


_lib: Optional[ctypes.CDLL] = None


def _get_lib() -> ctypes.CDLL:
    global _lib
    if _lib is None:
        _lib = _load_lib()
    return _lib


_HEADER_INIT_FMT = '<iiiii'  # head, tail, count, capacity, slot_size


def _init_ring_header(buf: memoryview, capacity: int, slot_payload_max: int) -> None:
    """Write capacity + slot_size into zero-filled SHM block (head/tail/count already 0)."""
    slot_size = _SHM_SLOT_HEADER_SIZE + slot_payload_max
    _struct.pack_into(_HEADER_INIT_FMT, buf, 0, 0, 0, 0, capacity, slot_size)
