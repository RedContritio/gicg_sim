"""Cross-language SHM ring backed by the ``gicg_actor/shm`` C library.

API: CrossLangShmRing(name, capacity, slot_payload_max, *, create=False).
See ``gicg_actor/shm/shm_ring.h`` and
``openspec/changes/archive/i29-go-actor-pool/shminf_design.md`` §D.

Platforms: macOS/Linux use ``shm_unix.c`` and Windows uses ``shm_win.c``.
On-demand Windows builds require GCC. POSIX native calls prepend ``/`` to
the SharedMemory name; Windows passes the name verbatim.

The native binding (ctypes signatures, ABI layout constants, on-demand
build) lives in :mod:`training.core.actor.ipc._shm_lib`.
"""

from __future__ import annotations

import ctypes
import struct as _struct
import sys
from multiprocessing.shared_memory import SharedMemory
from typing import Optional

from training.core.actor.ipc._shm_lib import (
    _LIB_FILENAME,
    _SHM_RING_HEADER_SIZE,
    _SHM_SLOT_HEADER_SIZE,
    _get_lib,
    _init_ring_header,
    _ring_total_size,
)


# ─── Public API ───────────────────────────────────────────────────────────────


class CrossLangShmRing:
    """Cross-language SHM ring backed by shm_open / CreateFileMapping + C11 atomics.

    Owner: ``CrossLangShmRing(name, ..., create=True)`` allocates + inits block;
    worker side attaches by the same bare name. Python SharedMemory handles
    unlink on ``close()`` (owner only). Args: name (bare, no leading slash),
    capacity (slot count), slot_payload_max (bytes per slot), create.
    """

    def __init__(
        self,
        name: str,
        capacity: int,
        slot_payload_max: int,
        *,
        create: bool = False,
    ) -> None:
        if _LIB_FILENAME is None:
            raise NotImplementedError(f'CrossLangShmRing: unsupported platform {sys.platform!r}')
        if capacity <= 0:
            raise ValueError(f'CrossLangShmRing: capacity must be > 0, got {capacity}')
        if slot_payload_max <= 0:
            raise ValueError(f'CrossLangShmRing: slot_payload_max must be > 0, got {slot_payload_max}')

        self.name = name
        self.capacity = capacity
        self.slot_payload_max = slot_payload_max
        self._total = _ring_total_size(capacity, slot_payload_max)
        self._owner = create
        self._closed = False

        lib = _get_lib()

        # SharedMemory manages OS lifecycle. C lib's shm_attach takes POSIX
        # "/<name>" on Mac/Linux vs bare name on Win (CPython passes name to
        # CreateFileMapping verbatim on Win — no prefix).
        self._shm = SharedMemory(name=name, create=create, size=self._total)
        if sys.platform == 'win32':
            self._native_name = self._shm.name.encode()
        else:
            self._native_name = ('/' + self._shm.name).encode()
        errno_val = ctypes.c_int(0)
        # Attach via C lib — needed for atomic ops.
        self._handle = lib.shm_attach(self._native_name, self._total, ctypes.byref(errno_val))
        if self._handle.ptr is None:
            self._shm.close()
            if create:
                self._shm.unlink()
            raise OSError(errno_val.value, f'CrossLangShmRing: shm_attach failed for {self._native_name!r}')

        if create:
            _init_ring_header(self._shm.buf, capacity, slot_payload_max)

        # Reusable output buffers (not thread-safe — one instance per thread).
        self._out_cid = ctypes.c_uint32(0)
        self._out_rid = ctypes.c_uint32(0)
        self._out_len = ctypes.c_uint32(0)
        self._out_buf = ctypes.create_string_buffer(slot_payload_max)

    @classmethod
    def attach(cls, name: str, capacity: int, slot_payload_max: int) -> 'CrossLangShmRing':
        """Attach to an existing ring created by the owner side.

        Equivalent to ``CrossLangShmRing(name, capacity, slot_payload_max, create=False)``.
        """
        return cls(name, capacity, slot_payload_max, create=False)

    def push(self, payload: bytes, *, client_id: int = 0, req_id: int = 0) -> bool:
        """Non-blocking push.  Returns False if full; raises ValueError if payload too large."""
        if len(payload) > self.slot_payload_max:
            raise ValueError(
                f'CrossLangShmRing.push: payload {len(payload)} > slot_payload_max {self.slot_payload_max}'
            )
        lib = _get_lib()
        rc = lib.shm_ring_push(
            self._handle,
            ctypes.c_uint32(client_id),
            ctypes.c_uint32(req_id),
            ctypes.c_char_p(payload),
            ctypes.c_uint32(len(payload)),
        )
        return rc == 1

    def try_pop(self) -> Optional[bytes]:
        """Non-blocking pop.  Returns None if empty, else raw payload bytes."""
        lib = _get_lib()
        rc = lib.shm_ring_pop(
            self._handle,
            ctypes.byref(self._out_cid),
            ctypes.byref(self._out_rid),
            self._out_buf,
            ctypes.byref(self._out_len),
            ctypes.c_uint32(self.slot_payload_max),
        )
        if rc == 0:
            return None
        return bytes(self._out_buf.raw[: self._out_len.value])

    def peek_count(self) -> int:
        """Read the diagnostic item count with relaxed atomic semantics."""
        # ``count`` is the int32 at header offset 8.
        try:
            count_bytes = bytes(self._shm.buf[8:12])
            return _struct.unpack('<i', count_bytes)[0]
        except Exception:
            return -1

    def peek_count_and_full_at_head(self) -> tuple[int, int]:
        """Return ``(count, full slots among the first count slots)``.

        The producer reserves count before marking a slot full, so readers may
        briefly observe a positive count with no committed slot. Interpret:

          (count, n_full):
            count > 0 and n_full == count    → all reserved slots committed
            count > 0 and n_full == 0        → transient reservation window
            count > 0 and n_full < count     → partially committed window
            count == 0                       → empty ring
            (-1, -1)                         → SHM read error

        This lock-free diagnostic is race-tolerant and caps scanning at the
        configured capacity.
        """
        buf = self._shm.buf
        try:
            head = _struct.unpack('<i', bytes(buf[0:4]))[0]
            count = _struct.unpack('<i', bytes(buf[8:12]))[0]
        except Exception:
            return (-1, -1)
        if count <= 0:
            return (count, 0)
        # Cap the scan if a concurrent update exposes a transient count.
        scan_n = count if count <= self.capacity else self.capacity
        slot_stride = _SHM_SLOT_HEADER_SIZE + self.slot_payload_max
        n_full = 0
        for i in range(scan_n):
            idx = (head + i) % self.capacity
            slot_off = _SHM_RING_HEADER_SIZE + idx * slot_stride
            try:
                status = buf[slot_off]  # u8 status byte at slot[idx][0]
            except Exception:
                break
            if status == 1:  # SHM_SLOT_FULL
                n_full += 1
        return (count, n_full)

    def try_pop_with_meta(self) -> Optional[tuple[int, int, bytes]]:
        """Non-blocking pop returning (client_id, req_id, payload).  None if empty."""
        lib = _get_lib()
        rc = lib.shm_ring_pop(
            self._handle,
            ctypes.byref(self._out_cid),
            ctypes.byref(self._out_rid),
            self._out_buf,
            ctypes.byref(self._out_len),
            ctypes.c_uint32(self.slot_payload_max),
        )
        if rc == 0:
            return None
        payload = bytes(self._out_buf.raw[: self._out_len.value])
        return (self._out_cid.value, self._out_rid.value, payload)

    def resp_write(self, payload: bytes, *, req_id: int = 0, timeout_ms: int = 0) -> bool:
        """Spin until single resp slot is EMPTY then write.  Returns False on timeout (0 = forever)."""
        if len(payload) > self.slot_payload_max:
            raise ValueError(
                f'CrossLangShmRing.resp_write: payload {len(payload)} > slot_payload_max {self.slot_payload_max}'
            )
        lib = _get_lib()
        rc = lib.shm_resp_write(
            self._handle,
            ctypes.c_uint32(req_id),
            ctypes.c_char_p(payload),
            ctypes.c_uint32(len(payload)),
            ctypes.c_int(timeout_ms),
        )
        return rc == 1

    def resp_read_blocking(self, timeout_ms: int) -> Optional[bytes]:
        """Spin until resp slot FULL and read.  Returns None on timeout.  timeout_ms must be > 0."""
        if timeout_ms <= 0:
            raise ValueError(f'CrossLangShmRing.resp_read_blocking: timeout_ms must be > 0, got {timeout_ms}')
        lib = _get_lib()
        out_rid = ctypes.c_uint32(0)
        out_len = ctypes.c_uint32(0)
        out_buf = ctypes.create_string_buffer(self.slot_payload_max)
        rc = lib.shm_resp_read(
            self._handle,
            ctypes.byref(out_rid),
            out_buf,
            ctypes.byref(out_len),
            ctypes.c_uint32(self.slot_payload_max),
            ctypes.c_int(timeout_ms),
        )
        if rc == 0:
            return None
        return bytes(out_buf.raw[: out_len.value])

    def close(self) -> None:
        """Detach mmap; owner also unlinks the SHM object."""
        if self._closed:
            return
        self._closed = True
        lib = _get_lib()
        lib.shm_detach(self._handle)
        try:
            self._shm.close()
        except Exception:
            pass
        if self._owner:
            try:
                self._shm.unlink()
            except Exception:
                pass

    def __enter__(self) -> 'CrossLangShmRing':
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __del__(self) -> None:
        try:
            self.close()
        except Exception:
            pass
