"""IPC queue wrapper — spawn-ctx multiprocessing.Queue.

Real multi-process queue (spawn ctx) used by InferenceServer ⟷ Client
RPC and by ActorRuntime for stop signalling. Wrapper exists so we have
one place to swap impl (e.g. ``faster_fifo``) without touching call sites.

The underlying ``ctx.Queue`` is picklable (mp ensures this) so wrapper
instances cross spawn boundaries cleanly.
"""

from __future__ import annotations

import queue as _queue
from typing import Any, Optional

from training.core.actor._mp_helpers import get_ctx


class IPCQueue:
    """Spawn-ctx mp.Queue wrapper. Picklable across process spawn."""

    def __init__(self, maxsize: int = 0) -> None:
        ctx = get_ctx()
        self._q = ctx.Queue(maxsize=maxsize)

    def put(self, item: Any, block: bool = True, timeout: Optional[float] = None) -> None:
        self._q.put(item, block=block, timeout=timeout)

    def put_nowait(self, item: Any) -> None:
        self._q.put_nowait(item)

    def get(self, block: bool = True, timeout: Optional[float] = None) -> Any:
        return self._q.get(block=block, timeout=timeout)

    def get_nowait(self) -> Any:
        return self._q.get_nowait()

    def empty(self) -> bool:
        return self._q.empty()

    def qsize(self) -> int:
        # macOS doesn't implement qsize on mp.Queue → fall back to 0.
        try:
            return self._q.qsize()
        except (NotImplementedError, OSError):
            return 0

    def close(self) -> None:
        try:
            # Drain any pending puts to avoid the join_thread deadlock that
            # happens if the writer thread still has buffered items.
            while True:
                try:
                    self._q.get_nowait()
                except _queue.Empty:
                    break
        except Exception:
            pass
        try:
            self._q.close()
        except Exception:
            pass
        try:
            self._q.join_thread()
        except Exception:
            pass

    def __getstate__(self):
        # Allow the wrapper to cross spawn boundaries — mp.Queue itself
        # is picklable when sent as a Process arg.
        return {'_q': self._q}

    def __setstate__(self, state):
        self._q = state['_q']
