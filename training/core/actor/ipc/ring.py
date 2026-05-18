"""SHM ring — real ``multiprocessing.shared_memory`` backed FIFO.

Fixed-capacity slot ring with per-slot pickle-byte payload. Slot layout:

    [ status:u8 | length:u32 | bytes[slot_payload_max] ]

``status`` is one of 0 (EMPTY) / 1 (FULL). Head/tail/count live in
shared ``mp.Value``\\s, all protected by one ``mp.Lock``. Bounded to
``capacity`` slots; ``push`` returns False if full (caller chooses to
drop or block); ``try_pop`` returns None when empty.

Records are pickled into the slot (so any picklable Python object
flows through). For very large objects choose a generous
``slot_payload_max`` — exceeding it raises ``ValueError`` at push.
"""

from __future__ import annotations

import pickle
import struct
from multiprocessing.shared_memory import SharedMemory
from typing import Any, Optional

from training.core.actor._mp_helpers import get_ctx, unique_name

_HEADER_FMT = '<BI'  # status:u8, length:u32
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)
_STATUS_EMPTY = 0
_STATUS_FULL = 1


class SHMRing:
    """Bounded SHM ring buffer for cross-process transition handoff.

    Args:
        capacity: number of slots.
        slot_payload_max: max pickle-byte payload per slot (default 256KiB).
        name: optional SHM block name; auto-generated if None.
        create: True for the owning side (allocates SHM); False to attach.

    Lifecycle: owner constructs with ``create=True`` then passes
    ``serialize()`` dict to workers; workers reattach via
    ``SHMRing.attach(serialized)``. Owner must ``close()`` (which
    unlinks the SHM block).
    """

    def __init__(
        self,
        capacity: int,
        slot_payload_max: int = 256 * 1024,
        name: Optional[str] = None,
        create: bool = True,
    ) -> None:
        if capacity <= 0:
            raise ValueError(f'SHMRing: capacity must be > 0, got {capacity}')
        if slot_payload_max <= 0:
            raise ValueError(f'SHMRing: slot_payload_max must be > 0, got {slot_payload_max}')
        self.capacity = capacity
        self.slot_payload_max = slot_payload_max
        self._slot_size = _HEADER_SIZE + slot_payload_max
        total = self._slot_size * capacity
        ctx = get_ctx()
        self._lock = ctx.Lock()
        self._head = ctx.Value('i', 0, lock=False)  # next pop idx
        self._tail = ctx.Value('i', 0, lock=False)  # next push idx
        self._count = ctx.Value('i', 0, lock=False)
        self._owner = create
        if create:
            self.name = name or unique_name('gicg_ring')
            self._shm = SharedMemory(create=True, size=total, name=self.name)
        else:
            if name is None:
                raise ValueError('SHMRing(create=False) requires name')
            self.name = name
            self._shm = SharedMemory(name=name)
        self._buf = self._shm.buf
        if create:
            # Zero-fill all slot headers so status starts EMPTY. macOS
            # rounds SHM size up to page granularity, so we only need to
            # touch the bytes our slot layout uses (not the whole buf).
            for i in range(capacity):
                struct.pack_into(_HEADER_FMT, self._buf, i * self._slot_size, _STATUS_EMPTY, 0)

    def push(self, item: Any) -> bool:
        """Pickle-and-write item into next free slot. Returns False if
        full (drops the item — caller's decision)."""
        payload = pickle.dumps(item, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > self.slot_payload_max:
            raise ValueError(
                f'SHMRing.push: payload {len(payload)} > slot_payload_max {self.slot_payload_max}',
            )
        with self._lock:
            if self._count.value >= self.capacity:
                return False
            slot_idx = self._tail.value
            off = slot_idx * self._slot_size
            struct.pack_into(_HEADER_FMT, self._buf, off, _STATUS_FULL, len(payload))
            self._buf[off + _HEADER_SIZE : off + _HEADER_SIZE + len(payload)] = payload
            self._tail.value = (slot_idx + 1) % self.capacity
            self._count.value += 1
            return True

    def try_pop(self) -> Optional[Any]:
        """Pop one item, return None if empty."""
        with self._lock:
            if self._count.value == 0:
                return None
            slot_idx = self._head.value
            off = slot_idx * self._slot_size
            status, length = struct.unpack_from(_HEADER_FMT, self._buf, off)
            if status != _STATUS_FULL:
                # Shouldn't happen — count says non-empty but slot empty.
                # Bail rather than mask state corruption.
                raise RuntimeError(f'SHMRing.try_pop: slot {slot_idx} EMPTY but count={self._count.value}')
            payload = bytes(self._buf[off + _HEADER_SIZE : off + _HEADER_SIZE + length])
            struct.pack_into(_HEADER_FMT, self._buf, off, _STATUS_EMPTY, 0)
            self._head.value = (slot_idx + 1) % self.capacity
            self._count.value -= 1
        return pickle.loads(payload)

    def pop(self) -> Any:
        """Pop one item — raise IndexError if empty."""
        item = self.try_pop()
        if item is None:
            raise IndexError('SHMRing: empty')
        return item

    def __len__(self) -> int:
        return self._count.value

    def serialize(self) -> dict:
        """Return a dict workers can pass to ``attach`` to rejoin."""
        return {
            'name': self.name,
            'capacity': self.capacity,
            'slot_payload_max': self.slot_payload_max,
            'head': self._head,
            'tail': self._tail,
            'count': self._count,
            'lock': self._lock,
        }

    @classmethod
    def attach(cls, info: dict) -> 'SHMRing':
        """Reconstruct a ring view on the worker side (does not own SHM)."""
        r = cls.__new__(cls)
        r.capacity = info['capacity']
        r.slot_payload_max = info['slot_payload_max']
        r._slot_size = _HEADER_SIZE + r.slot_payload_max
        r.name = info['name']
        r._owner = False
        r._lock = info['lock']
        r._head = info['head']
        r._tail = info['tail']
        r._count = info['count']
        r._shm = SharedMemory(name=r.name)
        r._buf = r._shm.buf
        return r

    # Spawn picklability ------------------------------------------------
    # ``self._buf`` is a memoryview backed by ``self._shm``; memoryview
    # is not picklable. Strip it on pickle and rehydrate by re-opening
    # the named SharedMemory on the worker side. The worker becomes a
    # non-owner view (no unlink on close).
    def __getstate__(self) -> dict:
        return {
            'name': self.name,
            'capacity': self.capacity,
            'slot_payload_max': self.slot_payload_max,
            '_slot_size': self._slot_size,
            '_lock': self._lock,
            '_head': self._head,
            '_tail': self._tail,
            '_count': self._count,
        }

    def __setstate__(self, state: dict) -> None:
        self.name = state['name']
        self.capacity = state['capacity']
        self.slot_payload_max = state['slot_payload_max']
        self._slot_size = state['_slot_size']
        self._lock = state['_lock']
        self._head = state['_head']
        self._tail = state['_tail']
        self._count = state['_count']
        self._owner = False
        self._shm = SharedMemory(name=self.name)
        self._buf = self._shm.buf

    def close(self) -> None:
        """Owner: unlink SHM. Worker: detach only."""
        try:
            self._buf = None
            self._shm.close()
        except Exception:
            pass
        if self._owner:
            try:
                self._shm.unlink()
            except Exception:
                pass
