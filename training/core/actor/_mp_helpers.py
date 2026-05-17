"""Multiprocessing helpers — spawn ctx, child env hardening, signal install.

All actor / inference / runtime modules go through ``get_ctx()`` so the
context choice is consistent (we explicitly use 'spawn' for macOS/Linux
parity — fork on Linux has surprising semantics around PyTorch + CUDA).
"""

from __future__ import annotations

import multiprocessing as mp
import os
import signal
import uuid
from typing import Optional

_CTX: Optional[mp.context.BaseContext] = None


def get_ctx() -> mp.context.BaseContext:
    """Return the project-wide spawn context (cached)."""
    global _CTX
    if _CTX is None:
        _CTX = mp.get_context('spawn')
    return _CTX


def harden_child_env() -> None:
    """Inside a worker — pin BLAS / OMP / MKL to 1 thread to avoid CPU
    oversubscription when N actors run concurrently. Idempotent."""
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
    except Exception:
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


def unique_name(prefix: str, total_max: int = 30) -> str:
    """Make a unique SHM / socket name. macOS POSIX SHM names are
    capped at 31 chars (incl. leading slash), so the default keeps the
    final name <= 30 chars by truncating the prefix as needed."""
    suffix = uuid.uuid4().hex[:8]
    # 1 char for separator '_'.
    max_prefix = max(1, total_max - 1 - len(suffix))
    short_prefix = prefix[:max_prefix]
    return f'{short_prefix}_{suffix}'
