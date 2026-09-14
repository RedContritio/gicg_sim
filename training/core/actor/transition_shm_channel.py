"""N-producer transition channel over ``CrossLangShmRing``.

Go actor processes push wire-v3 episode batches, and the Python driver
pulls raw bytes for a paradigm-specific decoder. This wrapper does not
decode payloads.

Lifecycle:
- ``create_owner`` allocates and initializes the block; owner close unlinks it.
- ``attach_worker`` opens an existing block; worker close only detaches.

See ``docs/superpowers/specs/2026-05-25-i29-redesign-design.md`` §4.2.
"""

from __future__ import annotations

from typing import Optional

from training.core.actor.ipc.ring_shm import CrossLangShmRing


class TransitionShmChannel:
    """Single-ring, multiple-producer transition channel."""

    def __init__(self, ring: CrossLangShmRing) -> None:
        self._ring = ring

    @classmethod
    def create_owner(cls, name: str, *, capacity: int, slot_size: int) -> 'TransitionShmChannel':
        """Allocate and initialize an owner block that unlinks on close."""
        ring = CrossLangShmRing(name, capacity, slot_size, create=True)
        return cls(ring)

    @classmethod
    def attach_worker(cls, name: str, *, capacity: int, slot_size: int) -> 'TransitionShmChannel':
        """Attach to an existing block without initializing or unlinking it."""
        ring = CrossLangShmRing(name, capacity, slot_size, create=False)
        return cls(ring)

    def push(self, payload: bytes, *, client_id: int = 0, req_id: int = 0) -> bool:
        """Push without blocking; return false when the ring is full."""
        return self._ring.push(payload, client_id=client_id, req_id=req_id)

    def try_pop(self) -> Optional[bytes]:
        """Pop without blocking; return ``None`` when the ring is empty."""
        return self._ring.try_pop()

    def try_pop_with_meta(self) -> Optional[tuple[int, int, bytes]]:
        """Pop ``(client_id, req_id, payload)`` without blocking."""
        return self._ring.try_pop_with_meta()

    def peek_count(self) -> int:
        """Read the diagnostic item count from the shared header."""
        return self._ring.peek_count()

    def peek_count_and_full_at_head(self) -> tuple[int, int]:
        """Return ``(count, full slots among the first count slots)``.

        This distinguishes a reserved but unwritten slot from an empty ring.
        """
        return self._ring.peek_count_and_full_at_head()

    def close(self) -> None:
        """Detach the mapping and unlink it when this channel owns it."""
        self._ring.close()

    def __enter__(self) -> 'TransitionShmChannel':
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
