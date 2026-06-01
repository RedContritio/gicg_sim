"""Unit tests for IPCQueue.close() — bounded + idempotent (I31 #88).

close() was the site of a SIGKILL'd-writer deadlock (a CFR actor killed
mid-traversal left the mp.Queue pipe half-written, and the old get_nowait()
drain blocked in os.read forever). The fix is cancel_join_thread() + close().
These lock the contract: close is non-blocking and safe to call twice. The
SIGKILL'd-writer scenario itself is exercised by the CFR mp e2e smoke_full.
"""

from __future__ import annotations

import time

from training.core.actor.ipc.queue import IPCQueue


def test_close_bounded_and_idempotent():
    """close() returns promptly and a second close() does not raise."""
    q = IPCQueue(maxsize=8)
    q.put(1)
    q.put(2)
    t0 = time.time()
    q.close()
    assert (time.time() - t0) < 5.0, 'IPCQueue.close hung'
    # Idempotent — calling again after the underlying queue is closed must not raise.
    q.close()


def test_close_with_buffered_items_does_not_block():
    """A queue with unread buffered items closes without joining the feeder
    (cancel_join_thread drops in-flight data — we don't care at shutdown)."""
    q = IPCQueue(maxsize=0)
    for i in range(50):
        q.put(i)
    t0 = time.time()
    q.close()
    assert (time.time() - t0) < 5.0, 'IPCQueue.close hung draining buffered items'
