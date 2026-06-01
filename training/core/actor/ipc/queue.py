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
        # cancel_join_thread drops any in-flight buffered items WITHOUT joining
        # the feeder thread — we don't care about pending data at shutdown.
        # This replaces a get_nowait() drain loop that DEADLOCKED when a writer
        # process was SIGKILL'd mid-put: a CFR actor killed mid-traversal (the
        # Go cgo call swallows SIGTERM, so the 2s grace expires → SIGKILL fires
        # mid-put) leaves the mp.Queue pipe in a state where get_nowait() blocks
        # in os.read forever instead of raising Empty. cancel_join_thread +
        # close is the bounded, non-blocking reader-side shutdown. Short-episode
        # paradigms (DMC/PPO) never hit the old hang (clean stop_event exit
        # before SIGKILL), so this is a strict improvement for all callers.
        # (See feedback_go_cgo_signal_handler.)
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
