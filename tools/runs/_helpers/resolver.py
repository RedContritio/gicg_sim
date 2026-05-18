"""tools.runs._helpers.resolver — R7 NNN shorthand → artifacts dir (T-05).

Internal module — callers must import from :mod:`tools.runs.helpers`.
Implements spec §CLI show 细则 HIGH-1-C 行 120-125 + §CLI mark 细则
HIGH-6-A 行 127-135 + §Public API helper 表 R7 行 545:

- shorthand ``69`` / ``069`` / ``000069`` all zero-pad to 6 digits, then
  exact match against ``artifacts/<ts>_<NNN>_<label>/``.
- 0 match → ``LookupError('NNN not found')`` (spec 行 310 prescribed wording).
- ≥2 match → ``LookupError('multiple dirs match <NNN>: <list>; please pass
  full dir path')`` (spec 行 311 prescribed wording; guards against
  cross-host sync silent collision per spec 行 123 + 131).
"""

from __future__ import annotations

import re
from pathlib import Path

_DIGITS_RE = re.compile(r'^\d{1,6}$')


def resolve_nnn_to_dir(repo_root: Path, nnn: str) -> Path:
    """Resolve a NNN shorthand (str) to its unique ``artifacts/`` dir.

    Per spec §CLI show 细则 HIGH-1-C + §CLI mark 细则 HIGH-6-A:

    - ``nnn`` must be 1-6 ASCII digit characters; ``zfill(6)`` then strict
      regex match ``^\\d{12}_<padded>_`` against each ``artifacts/`` child.
    - Exactly 1 match → return that ``Path``.
    - 0 match → raise ``LookupError('NNN not found')`` (spec line 310
      verbatim wording, then a path hint so the user knows where the
      scanner looked).
    - ≥2 match → raise ``LookupError('multiple dirs match <NNN>: <list>;
      please pass full dir path')`` (spec line 311 verbatim wording;
      candidates listed in sorted order for deterministic output).

    Why ``LookupError`` (not a custom exception class): stdlib semantic
    "key/value lookup failed" matches both 0 and ≥2 cases. callers
    (``show.py`` / ``mark.py``) can ``except LookupError`` without
    importing a custom class from this module, keeping the call sites
    simple. ``ValueError`` is reserved for input-shape errors (non-digit
    / wrong length), which are caller bugs rather than environmental
    misses.

    Args:
        repo_root: Repo root. Scans ``repo_root/artifacts/`` only.
        nnn: 1-6 digit string. ``'69'`` ↔ ``'069'`` ↔ ``'000069'`` all
            resolve to the same NNN ``000069`` after ``zfill(6)``.

    Returns:
        The unique matching ``Path`` (an existing dir under ``artifacts/``).

    Raises:
        ValueError: ``nnn`` is empty, longer than 6 chars, or contains
            non-digit characters.
        LookupError: 0 or ≥2 dirs match the zero-padded NNN.
    """
    if not _DIGITS_RE.match(nnn):
        raise ValueError(f'NNN {nnn!r} must be 1-6 digit string')

    nnn_padded = nnn.zfill(6)
    artifacts_dir = repo_root / 'artifacts'
    # Anchored regex ``^\d{12}_<padded>_`` per spec dir convention
    # `<ts>_<NNNNNN>_<label>` — the ``\d{12}`` prefix guard ensures
    # legacy pre-redesign dirs (e.g. ``r001_old/``,
    # ``pre_redesign_xxx/``) and the ``.run_id_lock`` file silently
    # skip. Built via concat (not ``.format``) since the regex itself
    # contains ``{12}`` quantifier braces that would clash with
    # ``str.format`` placeholder syntax.
    pattern = re.compile(r'^\d{12}_' + nnn_padded + r'_')

    candidates: list[Path] = []
    if artifacts_dir.exists():
        for entry in artifacts_dir.iterdir():
            if not entry.is_dir():
                continue
            if pattern.match(entry.name):
                candidates.append(entry)

    if not candidates:
        raise LookupError(f'NNN not found: {nnn_padded} (scanned {artifacts_dir})')

    if len(candidates) >= 2:
        sorted_names = sorted(c.name for c in candidates)
        raise LookupError(f'multiple dirs match {nnn_padded}: {sorted_names}; please pass full dir path')

    return candidates[0]
