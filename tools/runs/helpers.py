"""tools.runs.helpers — Public API helpers (clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`` §Public
API helper 表 行 533-547).

This module currently hosts R1-R4: path normalization, raw cfg checksum
(audit only), leaf-toml meta field extraction, and the kernel-tracked
NNN allocator. The remaining lock-ful helpers (R5-R7: per-run flock
context manager, atomic metadata writer, NNN→dir resolver) are scoped to
later tasks (T-04 / T-05) and intentionally not implemented here.

Stdlib only — no third-party deps. tomllib (Python ≥3.11) handles the TOML
parse. SHA-256 is content-only; mtime/size are intentionally excluded so
identical bytes always produce identical hashes (cross-host audit needs
that).
"""

from __future__ import annotations

import errno
import hashlib
import random
import re
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

# Platform-specific advisory file lock primitives. Imported eagerly so a
# bad host (e.g. exotic POSIX without fcntl) fails at import rather than
# mid-allocation when the allocator is first invoked.
if sys.platform == 'win32':
    import msvcrt
else:
    import fcntl

# Allocator-lock retry budget per spec §Atomic allocator 行 276 ("retry
# up to 10 次,每次 sleep random(0,50)ms;超时 raise 'unable to acquire
# run-id lock'"). Exposed module-level so tests can monkeypatch the
# sleep / random hooks without freezing CI.
_LOCK_RETRY_LIMIT = 10
_LOCK_RETRY_SLEEP_MAX_SECONDS = 0.05

# NNN dir naming per spec dir convention `<ts>_<NNNNNN>_<label>`. Anchored
# to ^ + \d{12} (12-digit timestamp prefix) so we don't accidentally
# match pre-redesign legacy dirs like `pre_redesign_xxx/` or
# `r001_yyy/` — those silently skip the max computation.
_NNN_DIR_RE = re.compile(r'^\d{12}_(\d{6})_')


def normalize_repo_relative(path: Path, repo_root: Path, label: str) -> str:
    """Return ``path`` as a repo-relative forward-slash POSIX string.

    Resolves both ``path`` and ``repo_root`` to absolute paths (following
    symlinks). Raises ``ValueError`` if the resolved ``path`` does not lie
    under ``repo_root``; the ``label`` is embedded in the error message to
    identify which field rejected the input (e.g. ``'cfg'`` /
    ``'artifacts'``).

    Always returns ``.as_posix()`` form. On Windows this converts
    backslash separators (``configs\\dmc\\x.toml``) to forward slashes
    (``configs/dmc/x.toml``); cross-host metadata sync would otherwise
    fail because POSIX receivers cannot resolve backslash paths.

    Symlink behavior: ``Path.resolve()`` follows symlinks. A repo-internal
    symlink pointing outside the tree is rejected; copy the target into
    the repo if you need it in metadata.
    """
    abs_path = path.resolve()
    abs_root = repo_root.resolve()
    try:
        rel = abs_path.relative_to(abs_root)
    except ValueError as e:
        raise ValueError(
            f'{label} path {str(path)!r} resolves to {str(abs_path)!r} which is outside repo root {str(abs_root)!r}'
        ) from e
    return rel.as_posix()


def cfg_checksum(cfg_path: Path) -> str:
    """Return ``'sha256:<64-hex>'`` of ``cfg_path``'s raw bytes.

    Audit-only — there is no drift guard built on this value (the old
    register/complete pipeline hashed the *merged effective* cfg for
    drift detection; that path is gone). Returns a content-only digest
    so two identical files in different locations hash identically.

    Propagates ``FileNotFoundError`` / ``IsADirectoryError`` / ``OSError``
    from the read — callers should not catch + silently default.
    """
    data = cfg_path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()
    return f'sha256:{digest}'


def extract_meta_field(cfg_path: Path, field: str) -> str | None:
    """Return ``cfg.meta.<field>`` from the leaf TOML at ``cfg_path``.

    Does NOT resolve ``meta.extends`` — reads ``cfg_path`` directly and
    inspects only its own ``[meta]`` table (per spec §Public API helper
    表 行 541 "无 extends resolve,纯本地 file 读 leaf toml"). If the leaf
    omits ``[meta]`` or the named field, returns ``None``.

    Strict type contract: if the field is present but not a string, raises
    ``TypeError``. The spec advertises a ``str | None`` return; silently
    coercing non-string values (e.g. ``42`` → ``'42'``) would mask cfg
    bugs.
    """
    data = tomllib.loads(cfg_path.read_text(encoding='utf-8'))
    meta = data.get('meta')
    if not isinstance(meta, dict):
        return None
    value = meta.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f'cfg {cfg_path} meta.{field} expected str, got {type(value).__name__}')
    return value


# --- R4: allocate_nnn --------------------------------------------------------


def _acquire_allocator_lock(fd) -> None:  # noqa: ANN001 — file object, not exposed
    """Acquire the kernel-tracked exclusive lock on ``fd`` non-blockingly.

    Linux/macOS use ``fcntl.flock(LOCK_EX | LOCK_NB)``; Windows uses
    ``msvcrt.locking(LK_NBLCK, 1)`` per spec §Atomic allocator 行 263.
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
        m = _NNN_DIR_RE.match(entry.name)
        if m is None:
            continue
        nnn = int(m.group(1))
        if nnn > max_nnn:
            max_nnn = nnn
    return max_nnn


@contextmanager
def allocate_nnn(repo_root: Path) -> Generator[int, None, None]:
    """Yield a fresh NNN under the allocator lock; caller mkdirs inside ``with``.

    Per spec §Atomic allocator 行 260-277:

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

    - 立即 mkdir ``<repo>/artifacts/<ts>_<NNN:06d>_<label>/`` (O_EXCL,
      ``exist_ok=False``) before exiting the ``with`` block — under
      lock — so the next allocator's ``_glob_max_nnn`` observes the
      new entry.
    - 如 ``FileExistsError`` (macOS case-insensitive FS 撞名 / cross-host
      sync stale dir leftover that didn't match the strict regex but
      happens to collide on the new name): exit the ``with`` block and
      re-enter ``allocate_nnn(repo_root)``. Lock release → re-glob
      observes the offending dir → the next loop's ``NNN`` will skip
      past the collision. spec 行 269-275 显式列此 retry pattern.
    - ``allocate_nnn`` 不内置 mkdir / 不内置 EEXIST retry — 选择 Option C
      (``@contextmanager`` yielding ``int``) 而非 callback-style
      ``allocate_nnn(repo_root, on_alloc=lambda nnn: ...)`` 是为保持
      helper 表 行 542 ``(repo_root) -> int`` 的 simplification. retry
      由 caller (T-08 ``train.py``) 显式控制。

    Signature note: spec helper table 行 542 advertises
    ``(repo_root: Path) -> int``. We implement as a context manager
    yielding ``int`` rather than a bare function because spec line 271
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
            hint is operator-actionable — spec 行 306 prescribes it
            verbatim so users know where to inspect.
    """
    artifacts_dir = repo_root / 'artifacts'
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_dir / '.run_id_lock'

    # `a+` opens for read+append, creating if missing — matches spec
    # line 266 exactly. The file content is irrelevant; we only need
    # the fd for flock.
    with open(lock_path, 'a+') as fd:
        acquired = False
        last_err: BaseException | None = None
        for attempt in range(_LOCK_RETRY_LIMIT):
            try:
                _acquire_allocator_lock(fd)
                acquired = True
                break
            except (BlockingIOError, OSError) as e:
                # Windows msvcrt raises plain OSError (errno EACCES /
                # EDEADLK) on lock contention; POSIX flock raises
                # BlockingIOError (EWOULDBLOCK). Treat both as
                # "contended, retry".
                if isinstance(e, OSError) and not isinstance(e, BlockingIOError):
                    contended_errnos = {
                        errno.EACCES,
                        errno.EAGAIN,
                        errno.EDEADLK,
                        getattr(errno, 'EWOULDBLOCK', errno.EAGAIN),
                    }
                    if e.errno not in contended_errnos:
                        # An unrelated OSError (e.g. EBADF on a closed
                        # fd) is a programmer bug — surface it instead
                        # of swallowing into the retry budget.
                        raise
                last_err = e
                # Skip sleep on the final attempt — we're about to give
                # up, no point waiting.
                if attempt < _LOCK_RETRY_LIMIT - 1:
                    time.sleep(random.uniform(0, _LOCK_RETRY_SLEEP_MAX_SECONDS))

        if not acquired:
            raise RuntimeError(
                'unable to acquire run-id lock after 10 retries; check artifacts/.run_id_lock'
            ) from last_err

        nnn = _glob_max_nnn(artifacts_dir) + 1
        yield nnn
        # flock auto-released on `with open` exit.
