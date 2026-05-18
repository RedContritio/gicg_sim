"""tools.runs._helpers.sync_extras — T-19 add-ons for :mod:`tools.runs.sync`.

Internal helper. Split out to keep ``sync.py`` under the 300-line
pre-commit budget once T-19 lands.

Three features:

- :func:`init_authoritative` — write ``artifacts/.authoritative_host`` =
  ``socket.gethostname()`` (spec §HIGH-2-D 行 348-356). Overwrite is OK
  per user decision (行 355). Marker file does not cross-host sync (the
  ``--exclude=artifacts/.authoritative_host`` rsync flag in ``sync.py``
  enforces that).
- :class:`CaseCollideError` + :func:`detect_case_collisions` — defend
  the macOS APFS (case-insensitive) ↔ Linux ext4 (case-sensitive) sync
  boundary (spec §CRIT-5-A 行 341-346). Two artifacts dirs that differ
  only by case would silently collide on APFS.
- :data:`REMOTE_RE_PATTERN` — the regex source string used by
  ``sync._REMOTE_RE``. Exposed here so the IPv6 alternative lives next
  to the case-collide / authoritative wording (single doc surface for
  T-19 spec §HIGH-6-B 行 441 + 行 493). Accepts:
  - ``user@hostname:path/`` (alphanum + dot + dash)
  - ``user@1.2.3.4:path/`` (IPv4 — same alphanum + dot + dash regex)
  - ``user@[::1]:path/`` / ``user@[fe80::1]:path/`` (IPv6 bracket form)
  Rejects: bare ``host:path/``, missing trailing ``/``, empty brackets,
  unterminated brackets, macOS local paths with colon.
"""

from __future__ import annotations

import socket
from pathlib import Path

__all__ = [
    'REMOTE_RE_PATTERN',
    'CaseCollideError',
    'detect_case_collisions',
    'init_authoritative',
]

# Spec §HIGH-6-B 行 441 / 行 493 — IPv6 bracket form must be accepted.
# Host part is an alternation: ``hostname-or-ipv4`` OR ``[ipv6]``.
# IPv6 inner: ``[0-9a-fA-F:]+`` — hex digits + colons, length ≥ 1 (empty
# ``[]`` rejected). Zone-id (``%eth0``) is allowed inside the bracket
# (the ``%`` char is intentionally excluded from the inner class so we
# stay strict here; widen later iff a real workflow needs it).
REMOTE_RE_PATTERN = r'^[A-Za-z0-9._-]+@(?:[A-Za-z0-9.-]+|\[[0-9a-fA-F:]+\]):.*/$'


class CaseCollideError(RuntimeError):
    """Two artifacts dir names differ only by case — would silently
    collide on case-insensitive filesystems (macOS APFS default).

    Raised before any rsync invocation so the user can rename one side
    before any cross-host transfer happens. Message lists every colliding
    pair so the user does not need to re-run to surface a second pair.
    """


def detect_case_collisions(dir_names: list[str]) -> list[tuple[str, str]]:
    """Find every pair ``(a, b)`` where ``a.lower() == b.lower()`` but
    ``a != b``. Exact duplicates (same casing repeated) are NOT a
    collision — they are the same identifier and reduce to one dir.

    Iteration order of the input list determines which name is reported
    first in each pair (the earlier-seen one). Pairs are returned in
    discovery order (each new collider against the first occurrence with
    that lowered key).

    >>> detect_case_collisions(['DMC', 'dmc'])
    [('DMC', 'dmc')]
    >>> detect_case_collisions(['DMC', 'DMC'])
    []
    >>> detect_case_collisions(['A', 'B', 'a'])
    [('A', 'a')]
    """
    seen: dict[str, str] = {}
    collisions: list[tuple[str, str]] = []
    for name in dir_names:
        low = name.lower()
        if low in seen:
            if seen[low] != name:
                collisions.append((seen[low], name))
        else:
            seen[low] = name
    return collisions


def init_authoritative(repo_root: Path, *, hostname: str | None = None) -> Path:
    """Write ``<repo_root>/artifacts/.authoritative_host`` =
    ``<hostname>\\n``. Creates ``artifacts/`` if missing.

    ``hostname`` is injectable for tests; defaults to
    :func:`socket.gethostname` at call time (NOT import time — tests
    monkeypatch the live binding). Overwrite of an existing marker is
    intentional (spec 行 355: user decision, ``overwrite OK``).

    Returns the absolute marker path so callers / tests can assert on
    location without re-deriving it.
    """
    if hostname is None:
        hostname = socket.gethostname()
    marker = repo_root / 'artifacts' / '.authoritative_host'
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(hostname + '\n', encoding='utf-8')
    return marker
