"""tools.runs._helpers.metadata_io — R6 atomic metadata writer.

Internal module — callers must import from :mod:`tools.runs.helpers`
(the public re-export shell). Wraps the per-run flock (R5) around a
same-directory temp-file + ``os.replace`` rename so concurrent writers
to the same artifacts_dir either both observe one whole payload or
get a clean ``RuntimeError`` after retry exhaustion.

Spec references:
- §metadata 写 行 283-286
- CRIT-2-B / CRIT-3-A (per-run lock scope; whole-payload writes)
- HIGH-5-B (explicit ban on ``tempfile.NamedTemporaryFile`` default
  args — its default dir is ``/tmp`` which may be a different mount,
  breaking ``os.replace`` atomicity)
"""

from __future__ import annotations

import os
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.locks import acquire_metadata_lock


def write_metadata_atomic(artifacts_dir: Path, metadata: schema.RunMetadata) -> None:
    """Atomically write ``metadata`` to ``<artifacts_dir>/metadata.toml``.

    Per spec §metadata 写 行 283-286 + CRIT-2-B / CRIT-3-A / HIGH-5-B:

    - Wraps the write in :func:`acquire_metadata_lock` (per-run flock).
    - Writes to a sibling temp file ``metadata.toml.tmp`` then
      ``os.replace`` — both paths under ``artifacts_dir`` so the rename
      stays on a single filesystem (cross-mount rename degenerates to
      copy+delete, breaking atomicity; HIGH-5-B explicit ban on
      ``tempfile.NamedTemporaryFile()`` default args because the default
      ``/tmp`` may be a different mount).
    - If the write or rename fails, the existing ``metadata.toml`` is
      left intact and the partial temp file is best-effort unlinked.

    :func:`schema.dumps` validates fields before serialization, so
    invalid metadata raises before any file IO happens.

    Note: Spec line 544 表表述 ``metadata: dict`` 是 simplification;实际实现
    接收 :class:`schema.RunMetadata` (strict typing,避免 caller 传 dict 时
    静默走 validate 失败)。Caller(T-08 train.py)必须先构 ``RunMetadata``
    再调本 helper。

    Warning: 本 helper 内部已 acquire :func:`acquire_metadata_lock`,**不要**
    在外层 already 持锁时调::

        with acquire_metadata_lock(d):
            write_metadata_atomic(d, m)  # ❌ deadlock

    正确用法:``write_metadata_atomic(d, m)`` 直接调,或在
    read-and-compare-and-write 场景由 caller 自己 lock + load + compare +
    ``write_metadata_atomic`` + dirty release 的 pattern(注意
    ``write_metadata_atomic`` 内会再 acquire — Linux flock cross-fd
    same-process 会 deadlock 至 retry 耗尽 raise;macOS BSD-flock per-fd
    不 deadlock 但仍非预期路径)。
    """
    target = artifacts_dir / 'metadata.toml'
    temp = artifacts_dir / 'metadata.toml.tmp'
    with acquire_metadata_lock(artifacts_dir):
        # Validate + serialize before opening any fd so a bad metadata
        # never even creates a temp file.
        payload = schema.dumps(metadata)
        try:
            temp.write_text(payload, encoding='utf-8')
            os.replace(temp, target)
        except BaseException:
            # Best-effort cleanup; never mask the original exception.
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            raise
