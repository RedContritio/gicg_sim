"""tools.runs._helpers.locks — advisory flock primitives + per-run
metadata lock (R5).

Internal module — callers must import from :mod:`tools.runs.helpers`
(the public re-export shell). Hosts the shared platform-dispatching
flock primitive and the spec-mandated 10-retry pattern used by both
the R4 allocator and the R5 per-run metadata lock.

Spec references:
- §Atomic allocator (flock dispatch + retry budget)
- §metadata 写 + CRIT-2-B / CRIT-3-A (per-run lock scope)
"""

from __future__ import annotations

import errno
import random
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

# Platform-specific advisory file lock primitives. Imported eagerly so a
# bad host (e.g. exotic POSIX without fcntl) fails at import rather than
# mid-allocation when a helper is first invoked.
if sys.platform == 'win32':
    import msvcrt
else:
    import fcntl

# Lock retry budget per spec §Atomic allocator ("retry up to 10 次,
# 每次 sleep random(0,50)ms;超时 raise 'unable to acquire ... lock'").
# Module-level so tests can monkeypatch the sleep / random hooks without
# freezing CI.
_LOCK_RETRY_LIMIT = 10
_LOCK_RETRY_SLEEP_MAX_SECONDS = 0.05


def _acquire_flock(fd) -> None:  # noqa: ANN001 — file object, not exposed
    """Acquire kernel-tracked exclusive lock on ``fd`` non-blockingly.

    Single platform dispatch point for every flock-using helper in this
    package (R4 allocator + R5 per-run metadata lock). Linux/macOS use
    ``fcntl.flock(LOCK_EX | LOCK_NB)``; Windows uses
    ``msvcrt.locking(LK_NBLCK, 1)`` per spec §Atomic allocator.
    Both APIs raise ``BlockingIOError`` / ``OSError`` when another
    process holds the lock; the caller's retry loop interprets that
    failure mode.
    """
    if sys.platform == 'win32':
        # msvcrt.locking locks `nbytes` starting at the current file
        # position. We seek to 0 so the lock region is deterministic
        # across processes (different starting positions would otherwise
        # produce non-overlapping locks — silent allocator races).
        fd.seek(0)
        msvcrt.locking(fd.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        fcntl.flock(fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _is_contended(e: OSError) -> bool:
    """Return True if ``e`` indicates lock contention (vs a real error).

    POSIX flock raises BlockingIOError (EWOULDBLOCK); Windows msvcrt
    raises plain OSError with errno in {EACCES, EAGAIN, EDEADLK}.
    Anything else (EBADF, EIO, …) is a programmer / IO bug — surface
    it instead of swallowing into the retry budget.
    """
    if isinstance(e, BlockingIOError):
        return True
    contended_errnos = {
        errno.EACCES,
        errno.EAGAIN,
        errno.EDEADLK,
        getattr(errno, 'EWOULDBLOCK', errno.EAGAIN),
    }
    return e.errno in contended_errnos


def _retry_acquire_flock(fd, *, timeout_msg: str) -> None:  # noqa: ANN001 — file object
    """Acquire flock on ``fd`` with the spec-mandated 10-retry budget.

    Shared between R4 allocator and R5 per-run metadata lock — both must
    use the same retry pattern per spec §Atomic allocator ("retry up to 10 次,每次
    sleep random(0,50)ms"). Sleep fires between attempts (not after
    the final one) so 10 attempts means 9 sleeps.

    Raises:
        RuntimeError: After ``_LOCK_RETRY_LIMIT`` failed attempts; the
            ``timeout_msg`` is used verbatim as the exception text and
            the last underlying ``BlockingIOError`` / ``OSError`` is
            chained as ``__cause__``.
    """
    last_err: BaseException | None = None
    for attempt in range(_LOCK_RETRY_LIMIT):
        try:
            _acquire_flock(fd)
            return
        except (BlockingIOError, OSError) as e:
            # BlockingIOError is an OSError subclass and _is_contended already
            # returns True for it, so a single _is_contended check
            # subsumes the previous nested isinstance dead branch.
            if not _is_contended(e):
                raise
            last_err = e
            if attempt < _LOCK_RETRY_LIMIT - 1:
                time.sleep(random.uniform(0, _LOCK_RETRY_SLEEP_MAX_SECONDS))
    raise RuntimeError(timeout_msg) from last_err


@contextmanager
def acquire_metadata_lock(artifacts_dir: Path) -> Generator[None, None, None]:
    """Yield while holding the per-run advisory lock at
    ``<artifacts_dir>/.metadata_lock`` (spec §metadata 写 +
    CRIT-2-B / CRIT-3-A).

    Per-run scope means two writers targeting the *same* run (e.g.
    train step 7 vs concurrent ``mark``) serialize, while writers
    targeting *different* runs never contend. Same flock + retry
    pattern as :func:`tools.runs.helpers.allocate_nnn` — kernel
    auto-releases on fd close.

    Raises:
        RuntimeError: After 10 failed retries, with a path-bearing
            hint so operators can inspect the lock file.
    """
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_dir / '.metadata_lock'
    with open(lock_path, 'a+') as fd:
        _retry_acquire_flock(
            fd,
            timeout_msg=f'unable to acquire metadata lock for {artifacts_dir} after 10 retries; check {lock_path}',
        )
        yield
