"""Multiprocessing helpers — spawn ctx, child env hardening, signal install.

All actor / inference / runtime modules go through ``get_ctx()`` so the
context choice is consistent (we explicitly use 'spawn' for macOS/Linux
parity — fork on Linux has surprising semantics around PyTorch + CUDA).
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import sys
import uuid
from pathlib import Path
from typing import Optional

_CTX: Optional[mp.context.BaseContext] = None


def get_ctx() -> mp.context.BaseContext:
    """Return the project-wide spawn context (cached)."""
    global _CTX
    if _CTX is None:
        _CTX = mp.get_context('spawn')
    return _CTX


def harden_child_env(affinity: Optional[list[int]] = None) -> None:
    """Inside a worker — pin BLAS / OMP / MKL to 1 thread to avoid CPU
    oversubscription when N actors run concurrently. Idempotent.

    ``affinity`` (optional): list of logical CPU IDs to pin this worker
    to via ``psutil.Process().cpu_affinity()``. Silently no-ops on
    platforms without cpu_affinity support (macOS) — affinity is a
    hint, not a contract; we'd rather skip than refuse to spawn the
    worker on Mac dev boxes."""
    for k in (
        'OMP_NUM_THREADS',
        'MKL_NUM_THREADS',
        'OPENBLAS_NUM_THREADS',
        'NUMEXPR_NUM_THREADS',
        'TORCH_NUM_THREADS',
    ):
        os.environ.setdefault(k, '1')
    try:
        import torch  # local import — avoid forcing torch on workers that don't need it

        torch.set_num_threads(1)
        # interop_threads pinned for the same oversubscription reason —
        # DouZero Phase 2 measurement showed it materially affects
        # per-actor throughput on multi-actor CPU runs.
        torch.set_num_interop_threads(1)
    except Exception:
        pass
    if affinity is not None:
        try:
            import psutil

            psutil.Process().cpu_affinity(affinity)
        except (ImportError, AttributeError, OSError):
            # Mac doesn't expose cpu_affinity on psutil.Process; also
            # silenced for missing psutil / kernel rejections. The
            # silent-skip is intentional: affinity is an optimization
            # hint, never a correctness requirement.
            pass


def install_quiet_sigterm(stop_event) -> None:
    """Worker-side signal handler — translate SIGTERM/SIGINT into a
    cooperative stop_event so the loop can clean up. Idempotent (safe
    to call multiple times in a worker)."""

    def _handler(signum, frame):  # pragma: no cover — signal context
        try:
            stop_event.set()
        except Exception:
            pass

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            # Background threads can't install signal handlers — ignore.
            pass


def setup_actor_file_logging(actor_id: int, cfg) -> None:
    """Tee this worker's stdout/stderr to ``<actor_log_dir>/actor_<id>.log``.

    mp child stdout/stderr is unreliable (pytest captures it, ssh strips it,
    sandboxes suppress it), so debugging mp crashes / silent hangs needs a
    file. Log dir from ``cfg.runtime.actor_log_dir`` (RuntimeCfg 缺失 →
    'artifacts/_actor_logs' default). On setup failure, falls back to the
    original stdout so the actor still runs — the setup exception goes to the
    original stderr so the parent process can see SOMETHING."""
    runtime = getattr(cfg, 'runtime', None)
    log_dir_str = getattr(runtime, 'actor_log_dir', None) or 'artifacts/_actor_logs'
    log_dir = Path(log_dir_str)
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f'actor_{actor_id}.log'
        # line-buffered so each print() is visible immediately even on crash
        log_f = open(log_path, 'w', buffering=1, encoding='utf-8')
        sys.stdout = log_f
        sys.stderr = log_f
        print(
            f'[actor {actor_id}] log start pid={os.getpid()} cfg.paradigm={getattr(cfg.meta, "paradigm", "?")}',
            flush=True,
        )
    except Exception as exc:  # noqa: BLE001
        print(f'[actor {actor_id}] log setup failed: {type(exc).__name__}: {exc}', file=sys.__stderr__)


def unique_name(prefix: str, total_max: int = 30) -> str:
    """Make a unique SHM / socket name. macOS POSIX SHM names are
    capped at 31 chars (incl. leading slash), so the default keeps the
    final name <= 30 chars by truncating the prefix as needed."""
    suffix = uuid.uuid4().hex[:8]
    # 1 char for separator '_'.
    max_prefix = max(1, total_max - 1 - len(suffix))
    short_prefix = prefix[:max_prefix]
    return f'{short_prefix}_{suffix}'
