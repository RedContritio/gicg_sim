"""IPC queue wrapper — spawn-ctx multiprocessing.Queue.

Real multi-process queue (spawn ctx) used as the actor→master transition
transport by the CFR / PPO async collectors (``paradigms.{cfr,ppo}._async``).
Wrapper exists so we have one place to swap impl (e.g. ``faster_fifo``)
without touching call sites. (The InferenceServer⟷Client RPC path uses raw
``ctx.Queue`` directly, not this wrapper.)

The underlying ``ctx.Queue`` is picklable (mp ensures this) so wrapper
instances cross spawn boundaries cleanly.
"""

from __future__ import annotations

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
        # Do not join the feeder thread during shutdown: a peer may have died
        # during a write, and pending transport data is disposable at this point.
        try:
            self._q.cancel_join_thread()
        except Exception:
            pass
        try:
            self._q.close()
        except Exception:
            pass

    def __getstate__(self):
        # Allow the wrapper to cross spawn boundaries — mp.Queue itself
        # is picklable when sent as a Process arg.
        return {'_q': self._q}

    def __setstate__(self, state):
        self._q = state['_q']
