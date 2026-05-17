"""Weights watcher — background thread polling WeightsSHM.

Spec: design/network-provider.md §1.1.

Local providers spawn a watcher that polls slot_latest at a fixed
interval; on version bump, calls the provider's update_weights with
the new state_dict."""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional


class WeightsWatcher:
    """Background thread polling WeightsSHM for a tag.

    Args:
        shm: WeightsSHM instance.
        tag: slot tag to poll.
        on_update: callback ``(state_dict, version)`` invoked when
            version advances.
        poll_interval_s: default 0.1 (100ms).
    """

    def __init__(
        self,
        shm,
        tag: str,
        on_update: Callable[[dict, int], None],
        poll_interval_s: float = 0.1,
    ) -> None:
        self.shm = shm
        self.tag = tag
        self.on_update = on_update
        self.poll_interval_s = poll_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._last_version: int = -1

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True, name=f'WeightsWatcher[{self.tag}]')
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            sd, v = self.shm.read(self.tag)
            if sd is not None and v > self._last_version:
                try:
                    self.on_update(sd, v)
                    self._last_version = v
                except Exception as e:
                    # Don't kill the thread on callback failure — log + continue.
                    print(f'[WeightsWatcher:{self.tag}] on_update failed: {type(e).__name__}: {e}')
            time.sleep(self.poll_interval_s)
