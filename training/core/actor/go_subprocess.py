"""Launch and manage the standalone ``cmd/gicg_actor`` executable.

The parent writes JSON configuration to stdin and waits for a ``READY``
line. Shutdown escalates from SIGTERM to SIGKILL after a timeout.
"""

from __future__ import annotations

import json
import queue
import re
import signal
import subprocess
import threading
import time
from typing import Any, Optional

# Backpressure line emitted periodically by ``gicg_actor/dmc/paradigm.go``:
#   [gicg_actor backpressure] actor=N ep=K push_total=T push_wait_ms=W.W push_drops=D
# The stderr reader keeps the latest per-actor snapshot for collector metrics.
_BACKPRESSURE_RE = re.compile(
    r'\[gicg_actor backpressure\] actor=(\d+) ep=(\d+) '
    r'push_total=(\d+) push_wait_ms=([\d.]+) push_drops=(\d+)'
)


def _drain_lines_to_queue(stream, q: 'queue.Queue[Optional[str]]') -> None:
    """Copy blocking line reads into a queue and append ``None`` at EOF.

    A reader thread works for subprocess pipes on both Windows and POSIX.
    """
    try:
        for line in iter(stream.readline, ''):
            q.put(line)
    except Exception:
        pass  # subprocess closed pipe — drained naturally
    finally:
        q.put(None)  # EOF sentinel


class GoSubprocessHandle:
    """Non-thread-safe handle for one Go actor subprocess."""

    def __init__(self, proc: subprocess.Popen) -> None:
        self._proc = proc
        self.returncode: Optional[int] = None

    @classmethod
    def spawn(
        cls,
        binary_path: str,
        config: dict[str, Any],
        *,
        ready_timeout_s: float = 30.0,
    ) -> 'GoSubprocessHandle':
        """Start the process, send configuration, and wait for ``READY``.

        Early exit or timeout raises ``RuntimeError``. A background reader
        handles stdout portably. ``go_mem_limit_mb`` is supplied in the JSON
        configuration; zero means unbounded.
        """
        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,  # line-buffered
        )
        # Send one complete config document, then close stdin.
        assert proc.stdin is not None
        try:
            proc.stdin.write(json.dumps(config) + '\n')
            proc.stdin.flush()
            proc.stdin.close()
        except BrokenPipeError:
            pass  # subprocess died before write — 下面 readline 会 catch

        # A daemon reader avoids platform-specific pipe polling.
        assert proc.stdout is not None
        stdout_q: 'queue.Queue[Optional[str]]' = queue.Queue()
        reader_thr = threading.Thread(
            target=_drain_lines_to_queue,
            args=(proc.stdout, stdout_q),
            daemon=True,
            name=f'gicg_actor[{proc.pid}]_stdout_reader',
        )
        reader_thr.start()

        # Drain stderr concurrently to prevent the child from blocking on a
        # full pipe, while retaining diagnostics and backpressure snapshots.
        assert proc.stderr is not None
        stderr_lines: list[str] = []
        bp_stats: dict[int, dict[str, Any]] = {}
        bp_lock = threading.Lock()

        def _drain_stderr() -> None:
            try:
                for line in iter(proc.stderr.readline, ''):
                    stderr_lines.append(line)
                    m = _BACKPRESSURE_RE.search(line)
                    if m:
                        actor_id = int(m.group(1))
                        with bp_lock:
                            bp_stats[actor_id] = {
                                'ep': int(m.group(2)),
                                'push_total': int(m.group(3)),
                                'push_wait_ms': float(m.group(4)),
                                'push_drops': int(m.group(5)),
                            }
            except Exception:
                pass

        stderr_thr = threading.Thread(
            target=_drain_stderr,
            daemon=True,
            name=f'gicg_actor[{proc.pid}]_stderr_reader',
        )
        stderr_thr.start()

        deadline = time.monotonic() + ready_timeout_s
        while True:
            if proc.poll() is not None:
                # Let the stderr reader finish before reporting startup failure.
                stderr_thr.join(timeout=0.5)
                stderr = ''.join(stderr_lines)
                raise RuntimeError(f'Go subprocess exited (rc={proc.returncode}) before READY: {stderr}')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                proc.kill()
                proc.wait(timeout=5.0)
                raise RuntimeError(f'Go subprocess did not signal READY within {ready_timeout_s}s')
            try:
                line = stdout_q.get(timeout=min(remaining, 0.1))
            except queue.Empty:
                continue
            if line is None:
                # The next poll reports the process exit.
                continue
            line = line.strip()
            if line == 'READY':
                break
            # Forward non-protocol output for diagnostics.
            print(f'[gicg_actor stdout] {line}', flush=True)

        handle = cls(proc)
        handle._bp_stats = bp_stats  # type: ignore[attr-defined]
        handle._bp_lock = bp_lock  # type: ignore[attr-defined]
        return handle

    def get_backpressure_stats(self) -> dict[int, dict[str, Any]]:
        """Return the latest per-actor backpressure counters."""
        bp_stats = getattr(self, '_bp_stats', None)
        bp_lock = getattr(self, '_bp_lock', None)
        if bp_stats is None or bp_lock is None:
            return {}
        with bp_lock:
            return {aid: dict(s) for aid, s in bp_stats.items()}

    def alive(self) -> bool:
        """Report liveness and capture the return code after exit."""
        if self._proc.poll() is None:
            return True
        self.returncode = self._proc.returncode
        return False

    def terminate(self, *, timeout_s: float = 10.0) -> None:
        """Request SIGTERM, then use SIGKILL after the timeout."""
        if not self.alive():
            return
        self._proc.send_signal(signal.SIGTERM)
        try:
            self.returncode = self._proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            self._proc.kill()
            self.returncode = self._proc.wait(timeout=5.0)
