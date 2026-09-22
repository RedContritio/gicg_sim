"""tools.runs._helpers.allocator — R4 NNN allocator under flock (T-03).

Internal module — callers must import from :mod:`tools.runs.helpers`
(the public re-export shell). Implements the spec §Atomic allocator flow: scan ``artifacts/`` for the highest existing 6-digit
NNN, return ``max + 1`` under exclusive lock, let the caller mkdir the
new artifacts subdir inside the critical section.
"""

from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from tools.runs._helpers.locks import _retry_acquire_flock

# NNN dir naming per spec dir convention `<ts>_<NNNNNN>` (legacy runs may
# retain a `<label>` suffix). Anchored
# to ^ + \d{12} (12-digit timestamp prefix) so we don't accidentally
# match pre-redesign legacy dirs like `pre_redesign_xxx/` or
# `r001_yyy/` — those silently skip the max computation.
_NNN_DIR_RE = re.compile(r'^\d{12}_(\d{6})(?:_|$)')


def _glob_max_nnn(artifacts_dir: Path) -> int:
    """Return the highest NNN currently in ``artifacts_dir/``, or 0 if empty.

    Scans every immediate child dir; matches ``^\\d{12}_(\\d{6})_`` and
    extracts the 6-digit NNN. Non-matching names (legacy ``r001_*``,
    pre-redesign dumps, ``.run_id_lock`` file, etc.) are silently
    skipped — they cannot collide with the new allocator scheme.
    """
    max_nnn = 0
    if not artifacts_dir.exists():
        return 0
    for entry in artifacts_dir.iterdir():
        if not entry.is_dir():
            continue
        candidates = [entry]
        if not _NNN_DIR_RE.match(entry.name):
            candidates = [child for child in entry.iterdir() if child.is_dir()]
        for candidate in candidates:
            m = _NNN_DIR_RE.match(candidate.name)
            if m is None:
                continue
            nnn = int(m.group(1))
            if nnn > max_nnn:
                max_nnn = nnn
    return max_nnn


@contextmanager
def allocate_nnn(repo_root: Path) -> Generator[int, None, None]:
    """Yield a fresh NNN under the allocator lock; caller mkdirs inside ``with``.

    Per spec §Atomic allocator:

    - ``open('artifacts/.run_id_lock', 'a+')`` + ``fcntl.flock(LOCK_EX |
      LOCK_NB)``; kernel auto-releases on fd close so a crashed process
      never leaves a stale lock (the failure mode that motivated
      replacing the old O_EXCL marker scheme — round-4 CRIT-4-A).
    - On ``BlockingIOError`` retry up to 10 times, sleeping
      ``random.uniform(0, 50ms)`` between attempts. Past budget raise
      ``RuntimeError('unable to acquire run-id lock after 10 retries')``.
    - Inside the lock: ``glob_max_NNN() + 1`` → yield to caller, who
      must perform the exclusive mkdir of the new artifacts subdir.
      Caller MUST do the mkdir before exiting the ``with`` block — that
      keeps the spec invariant "mkdir is inside the critical section"
      so two concurrent allocators see each other's dirs on the
      subsequent re-glob.

    Caller 责任 (within ``with`` body):

    - 立即 mkdir ``<repo>/artifacts/<experiment_tag>/<ts>_<NNN:06d>/`` (O_EXCL,
      ``exist_ok=False``) before exiting the ``with`` block — under
      lock — so the next allocator's ``_glob_max_nnn`` observes the
      new entry.
    - 如 ``FileExistsError`` (macOS case-insensitive FS 撞名 / cross-host
      sync stale dir leftover that didn't match the strict regex but
      happens to collide on the new name): exit the ``with`` block and
      re-enter ``allocate_nnn(repo_root)``. Lock release → re-glob
      observes the offending dir → the next loop's ``NNN`` will skip
      past the collision. spec §Atomic allocator 显式列此 retry pattern.
    - ``allocate_nnn`` 不内置 mkdir / 不内置 EEXIST retry — 选择 Option C
      (``@contextmanager`` yielding ``int``) 而非 callback-style
      ``allocate_nnn(repo_root, on_alloc=lambda nnn: ...)`` 是为保持
      §Public API helper 表 ``(repo_root) -> int`` 的 simplification. retry
      由 caller (T-08 ``train.py``) 显式控制。

    Signature note: spec helper table §Public API helper 表 HIGH-5-A advertises
    ``(repo_root: Path) -> int``. We implement as a context manager
    yielding ``int`` rather than a bare function because spec §Atomic allocator
    requires the new-dir ``mkdir`` to happen *inside* the lock. A bare
    ``-> int`` function would have to release the lock before returning,
    re-introducing a race window (two callers both observe the same
    ``max`` before either mkdirs). ``with`` semantics let the caller
    mkdir under lock while keeping the public surface "give me an NNN"
    — the spec signature is a simplification, this is the safe form.

    Args:
        repo_root: Repo root. The lock file lives at
            ``<repo_root>/artifacts/.run_id_lock``; the ``artifacts/``
            dir is auto-created if missing (the lock file's parent
            must exist for ``open('a+')``).

    Yields:
        int: The newly allocated NNN (not zero-padded — caller is
        responsible for ``f'{nnn:06d}'`` formatting). Always ``>= 1``.

    Raises:
        RuntimeError: After 10 retries failing to acquire the
            allocator lock (``'unable to acquire run-id lock after 10
            retries; check artifacts/.run_id_lock'``). The trailing
            hint is operator-actionable — spec §用户友好 error message prescribes it
            verbatim so users know where to inspect.
    """
    artifacts_dir = repo_root / 'artifacts'
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_dir / '.run_id_lock'

    # `a+` opens for read+append, creating if missing — matches spec
    # §Atomic allocator exactly. The file content is irrelevant; we only need
    # the fd for flock.
    with open(lock_path, 'a+') as fd:
        _retry_acquire_flock(
            fd,
            timeout_msg='unable to acquire run-id lock after 10 retries; check artifacts/.run_id_lock',
        )
        nnn = _glob_max_nnn(artifacts_dir) + 1
        yield nnn
        # flock auto-released on `with open` exit.
