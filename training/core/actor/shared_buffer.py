"""SharedBufferAdapter — drain SHM ring (or mp.Queue) → learner Buffer.

The ring/queue carries actor-pushed payloads. Two shapes are accepted:

- ``list[Transition]`` (raw, what :func:`actor_main` pushes by default)
- :class:`CollectorOutput` (paradigm-side adapter has already wrapped)

This is the seam between IPC (transitions land in SHM) and the in-proc
Buffer the learner samples from. Driver calls ``drain()`` periodically.
"""

from __future__ import annotations

import queue as _queue
from typing import Any

from training.core.actor.ipc.ring import SHMRing
from training.core.protocols import Buffer, CollectorOutput


class SharedBufferAdapter:
    """Pull-side. Tolerant of either :class:`SHMRing` or any object
    exposing ``try_pop()`` / ``get_nowait()``."""

    def __init__(self, source: Any, buffer: Buffer) -> None:
        self.source = source
        self.buffer = buffer

    def _try_pop(self):
        if isinstance(self.source, SHMRing) or hasattr(self.source, 'try_pop'):
            return self.source.try_pop()
        # mp.Queue / IPCQueue
        try:
            return self.source.get_nowait()
        except _queue.Empty:
            return None

    def drain(self, max_items: int = 1024) -> int:
        """Pull up to max_items batches from source → buffer. Returns
        items drained."""
        n = 0
        while n < max_items:
            item = self._try_pop()
            if item is None:
                break
            if isinstance(item, CollectorOutput):
                self.buffer.push(item)
            elif hasattr(item, 'transitions'):
                self.buffer.push(item)
            else:
                # Assume list[Transition] — wrap.
                self.buffer.push(CollectorOutput(transitions=list(item), episode_stats=[]))
            n += 1
        return n

    def close(self) -> None:
        if hasattr(self.source, 'close'):
            try:
                self.source.close()
            except Exception:
                pass
