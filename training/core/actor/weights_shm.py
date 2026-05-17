"""Weights SHM — multi-slot weights store via ``shared_memory``.

Slot layout (per tag):

    [ version:i64 | length:u32 | bytes[max_state_dict_bytes] ]

Each slot has its own named ``SharedMemory`` block + a process-shared
``mp.Lock`` for atomic writes. Readers see a consistent (version,
state_dict) tuple — never a torn write.

The slot map is a plain dict; workers attach by being handed a
serialized snapshot at spawn time (``serialize_for_worker(tags) →
dict`` + ``WeightsSHM.attach(info)``). The parent retains write
authority for all slots. Snapshot slots (e.g. ``snapshot_eval_<id>``)
live only on the parent — eval workers either attach explicitly via
``attach()`` with the slot info, or read via parent-mediated handoff.
"""

from __future__ import annotations

import pickle
import struct
from multiprocessing.shared_memory import SharedMemory
from typing import Optional

from training.core.actor._mp_helpers import get_ctx, unique_name

_HEADER_FMT = '<qI'  # version:i64, length:u32
_HEADER_SIZE = struct.calcsize(_HEADER_FMT)


class _SHMSlot:
    """One named SHM block + an mp.Lock guarding writes. Picklable so
    workers can ``read()`` after spawn."""

    def __init__(self, name: str, size: int, lock, create: bool = True) -> None:
        self.name = name
        self.size = size
        self.lock = lock
        self._owner = create
        if create:
            self._shm = SharedMemory(create=True, size=size, name=name)
            # Cold marker — version=-1.
            struct.pack_into(_HEADER_FMT, self._shm.buf, 0, -1, 0)
        else:
            self._shm = SharedMemory(name=name)

    @property
    def buf(self):
        return self._shm.buf

    def close(self) -> None:
        try:
            self._shm.close()
        except Exception:
            pass
        if self._owner:
            try:
                self._shm.unlink()
            except Exception:
                pass

    def __getstate__(self):
        # Workers reattach by name; lock pickles through ctx automatically.
        return {'name': self.name, 'size': self.size, 'lock': self.lock}

    def __setstate__(self, st):
        self.name = st['name']
        self.size = st['size']
        self.lock = st['lock']
        self._shm = SharedMemory(name=self.name)
        self._owner = False


class WeightsSHM:
    """Multi-slot weights store backed by SharedMemory.

    Args:
        max_state_dict_bytes: max serialized state_dict size per slot
            (default 128 MiB).
        owner: True for parent (creates slots); False for worker
            (attached via ``WeightsSHM.attach``).
    """

    def __init__(
        self,
        max_state_dict_bytes: int = 128 * 1024 * 1024,
        owner: bool = True,
    ) -> None:
        self._ctx = get_ctx()
        self._slots: dict = {}
        self._slot_create_lock = self._ctx.Lock() if owner else None
        self.max_state_dict_bytes = max_state_dict_bytes
        self._owner = owner

    def _ensure_slot(self, tag: str) -> _SHMSlot:
        slot = self._slots.get(tag)
        if slot is not None:
            return slot
        if not self._owner:
            raise KeyError(f'WeightsSHM(attached).{tag!r}: slot not attached; parent must create + share name')
        with self._slot_create_lock:
            slot = self._slots.get(tag)
            if slot is not None:
                return slot
            name = unique_name(f'gicg_w_{tag}')
            size = _HEADER_SIZE + self.max_state_dict_bytes
            slot = _SHMSlot(name=name, size=size, lock=self._ctx.Lock(), create=True)
            self._slots[tag] = slot
            return slot

    def write(self, tag: str, state_dict: dict, version: int) -> None:
        payload = pickle.dumps(state_dict, protocol=pickle.HIGHEST_PROTOCOL)
        if len(payload) > self.max_state_dict_bytes:
            raise ValueError(
                f'WeightsSHM.write[{tag}]: state_dict {len(payload)}B '
                f'> max {self.max_state_dict_bytes}B — bump WeightsSHM(max_state_dict_bytes=...)',
            )
        slot = self._ensure_slot(tag)
        with slot.lock:
            struct.pack_into(_HEADER_FMT, slot.buf, 0, version, len(payload))
            slot.buf[_HEADER_SIZE : _HEADER_SIZE + len(payload)] = payload

    def read(self, tag: str) -> tuple:
        """Return ``(state_dict, version)``. Cold/missing → ``(None, -1)``."""
        slot = self._slots.get(tag)
        if slot is None:
            return None, -1
        with slot.lock:
            version, length = struct.unpack_from(_HEADER_FMT, slot.buf, 0)
            if version < 0 or length == 0:
                return None, -1
            payload = bytes(slot.buf[_HEADER_SIZE : _HEADER_SIZE + length])
        return pickle.loads(payload), version

    def snapshot(self, src_tag: str, dst_tag: str) -> int:
        """Copy src slot bytes → dst (creates dst if missing). Returns
        version snapshot was taken at."""
        src = self._slots.get(src_tag)
        if src is None:
            raise KeyError(f'WeightsSHM.snapshot: src tag {src_tag!r} missing')
        dst = self._ensure_slot(dst_tag)
        a, b = sorted([(src_tag, src), (dst_tag, dst)], key=lambda kv: kv[0])
        with a[1].lock:
            with b[1].lock:
                version, length = struct.unpack_from(_HEADER_FMT, src.buf, 0)
                dst.buf[: _HEADER_SIZE + length] = bytes(src.buf[: _HEADER_SIZE + length])
        return version

    def list_tags(self) -> list:
        return list(self._slots.keys())

    def drop(self, tag: str) -> None:
        slot = self._slots.pop(tag, None)
        if slot is not None:
            slot.close()

    def close(self) -> None:
        for tag in list(self._slots.keys()):
            self.drop(tag)

    # ---------- worker attach API ---------- #
    def serialize_for_worker(self, tags: list) -> dict:
        """Return picklable dict workers reconstruct via ``attach``. Only
        the requested tags are shared (workers don't need eval-snapshot
        slots)."""
        return {
            'max_state_dict_bytes': self.max_state_dict_bytes,
            'slots': {t: self._slots[t] for t in tags if t in self._slots},
        }

    @classmethod
    def attach(cls, info: dict) -> 'WeightsSHM':
        """Construct a read-only attached view (worker-side)."""
        shm = cls(max_state_dict_bytes=info['max_state_dict_bytes'], owner=False)
        shm._slots = dict(info['slots'])  # _SHMSlot.__setstate__ rebinds SHM
        return shm


def latest_version(shm: WeightsSHM, tag: str = 'latest') -> Optional[int]:
    """Helper — ``None`` if no slot, else current version."""
    _, v = shm.read(tag)
    return None if v < 0 else v
