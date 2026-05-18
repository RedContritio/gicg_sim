"""tools.runs._helpers.sync_scan — local + remote metadata.timestamp scan.

Internal helper for :mod:`tools.runs.sync`. Split out to keep sync.py under
the 300-line pre-commit budget.

Two public functions:
- ``scan_local_timestamps`` — glob ``<root>/artifacts/<run_dir>/metadata.toml``
- ``scan_remote_timestamps`` — SSH + ``find … -exec cat`` then parse blocks
- ``parse_remote_find_output`` — pure parser, exposed for unit tests
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

# Dir-name shape per spec §Per-run 行 79: ``<YYYYMMDDHHMM>_<NNNNNN>_<label>``.
_RUN_DIR_RE = re.compile(r'^\d{12}_(\d{6})_(.+)$')


def scan_local_timestamps(local_root: Path) -> dict[str, str]:
    """Return ``{nnn: timestamp}`` for every well-formed local metadata.toml.

    Malformed metadata (parse fail / missing timestamp) → silently skipped;
    those NNN simply don't participate in conflict detection. The audit
    warn is left to :mod:`tools.runs.list`.
    """
    out: dict[str, str] = {}
    artifacts = local_root / 'artifacts'
    if not artifacts.is_dir():
        return out
    for entry in artifacts.iterdir():
        if not entry.is_dir():
            continue
        m = _RUN_DIR_RE.match(entry.name)
        if m is None:
            continue
        nnn = m.group(1)
        meta_path = entry / 'metadata.toml'
        if not meta_path.is_file():
            continue
        try:
            data = tomllib.loads(meta_path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        ts = data.get('timestamp')
        if not isinstance(ts, str) or not ts:
            continue
        out[nnn] = ts
    return out


def _parse_user_host_path(remote: str) -> tuple[str, str]:
    """Split ``user@host:path/`` into ``(user@host, path)``. Caller has
    already validated the form."""
    user_host, path = remote.split(':', 1)
    return user_host, path


def scan_remote_timestamps(remote: str, *, runner=None) -> dict[str, str]:
    """SSH to remote host + emit one ``===FILE / body / ===END`` block per
    ``<remote_path>/artifacts/*/metadata.toml``, then parse into
    ``{nnn: timestamp}``.

    Empty dict on SSH failure (treated as "no remote runs known"). ``runner``
    injectable for tests.
    """
    if runner is None:
        runner = subprocess.run
    user_host, remote_path = _parse_user_host_path(remote)
    remote_cmd = (
        f'cd {shlex.quote(remote_path.rstrip("/"))} && '
        'find artifacts -maxdepth 2 -name metadata.toml -type f '
        '-exec sh -c \'printf "===FILE %s\\n" "$1"; cat "$1"; printf "\\n===END\\n"\' _ {} \\;'
    )
    try:
        result = runner(
            ['ssh', user_host, remote_cmd],
            capture_output=True,
            text=True,
            check=False,
        )
    except (FileNotFoundError, OSError):
        return {}
    if result.returncode != 0:
        return {}
    return parse_remote_find_output(result.stdout)


def parse_remote_find_output(text: str) -> dict[str, str]:
    """Parse ``===FILE <path>\\n<body>\\n===END\\n`` blocks → ``{nnn: ts}``.

    Robust to extra whitespace, malformed TOML in body (silently skipped),
    paths that don't match the run-dir regex (silently skipped).
    """
    out: dict[str, str] = {}
    blocks = re.split(r'^===FILE ', text, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        head, _, rest = block.partition('\n')
        file_path = head.strip()
        body = rest.split('\n===END', 1)[0]
        # Path shape: ``artifacts/<run_dir>/metadata.toml``.
        parts = file_path.split('/')
        if len(parts) < 3 or parts[0] != 'artifacts' or parts[-1] != 'metadata.toml':
            continue
        m = _RUN_DIR_RE.match(parts[-2])
        if m is None:
            continue
        nnn = m.group(1)
        try:
            data = tomllib.loads(body)
        except ValueError:
            continue
        ts = data.get('timestamp')
        if isinstance(ts, str) and ts:
            out[nnn] = ts
    return out
