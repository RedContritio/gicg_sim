"""tools.runs._helpers.sync_scan — local + remote metadata.timestamp scan.

Internal helper for :mod:`tools.runs.sync`. Split out to keep sync.py under
the 300-line pre-commit budget.

Public functions:
- ``scan_local_timestamps`` — glob ``<root>/artifacts/<run_dir>/metadata.toml``
- ``scan_remote_timestamps`` — cfg-driven remote scan then parse blocks
- ``parse_remote_find_output`` — pure parser, exposed for unit tests
- ``scan_local_dir_names`` — list run-dir names locally (case-collide input, T-19)
- ``parse_remote_dir_names`` — list run-dir names from the same SSH output (T-19)
"""

from __future__ import annotations

import re
import shlex
import tomllib
from pathlib import Path

from tools.runs._host import RemoteCfg, ps_quote, ssh_run, ssh_run_bash
from tools.runs._helpers.paths import RUN_DIR_RE, iter_run_dirs


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
    for entry in iter_run_dirs(local_root):
        m = RUN_DIR_RE.match(entry.name)
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


def _remote_scan_script(remote: RemoteCfg) -> str:
    if remote.os == 'windows':
        root = ps_quote(remote.root_native)
        return (
            f"$artifacts = Join-Path {root} 'artifacts'; "
            'if (Test-Path -LiteralPath $artifacts) { '
            "Get-ChildItem -LiteralPath $artifacts -Directory -Recurse | Where-Object { $_.Name -eq 'metadata.toml' } | ForEach-Object { "
            '$file = $_.FullName; '
            'if (Test-Path -LiteralPath $file -PathType Leaf) { '
            "$rel = $_.FullName.Substring($artifacts.FullName.Length).TrimStart('\\','/').Replace('\\','/'); "
            "Write-Output ('===FILE artifacts/' + $rel); "
            "Get-Content -Raw -LiteralPath $file; Write-Output ''; Write-Output '===END' } } }"
        )
    root = shlex.quote(remote.root.rstrip('/'))
    return (
        f'cd {root} && if [ -d artifacts ]; then '
        'find artifacts -maxdepth 3 -name metadata.toml -type f '
        '-exec sh -c \'printf "===FILE %s\\n" "$1"; cat "$1"; printf "\\n===END\\n"\' _ {} \\;; fi'
    )


def fetch_remote_find_text(remote: RemoteCfg, *, runner=None) -> str:
    """Run the remote metadata scan once and return raw stdout text.

    Both :func:`parse_remote_find_output` (timestamps) and
    :func:`parse_remote_dir_names` (case-collide input) consume the same
    block stream — surface this single fetch so we don't pay the SSH RTT
    twice (T-19 case-collide wiring).
    """
    if runner is None:
        runner = ssh_run if remote.os == 'windows' else ssh_run_bash
    script = _remote_scan_script(remote)
    try:
        result = runner(remote, script)
    except (FileNotFoundError, OSError) as e:
        raise RuntimeError(f'remote scan failed for {remote.ssh}: {e}') from e
    if result.returncode != 0:
        detail = (result.stderr or '').strip()
        suffix = f': {detail}' if detail else ''
        raise RuntimeError(f'remote scan failed for {remote.ssh} (exit {result.returncode}){suffix}')
    return result.stdout


def scan_remote_timestamps(remote: RemoteCfg, *, runner=None) -> dict[str, str]:
    """Scan remote host + emit one ``===FILE / body / ===END`` block per
    ``<remote_path>/artifacts/*/metadata.toml``, then parse into
    ``{nnn: timestamp}``.

    SSH failures raise instead of being treated as an empty remote. ``runner``
    injectable for tests.
    """
    return parse_remote_find_output(fetch_remote_find_text(remote, runner=runner))


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
        m = RUN_DIR_RE.match(parts[-2])
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


def scan_local_dir_names(local_root: Path) -> list[str]:
    """Return every well-formed run-dir name under ``<local_root>/artifacts/``.

    Used by case-collide detection (spec §CRIT-5-A); we need
    the full ``<ts>_<NNN>_<label>`` name (not the parsed NNN) so case
    differences in the label portion are surfaced (``..._DMC`` vs
    ``..._dmc`` would silently collide on macOS APFS).
    """
    artifacts = local_root / 'artifacts'
    if not artifacts.is_dir():
        return []
    names: list[str] = []
    for entry in iter_run_dirs(local_root):
        if RUN_DIR_RE.match(entry.name) is None:
            continue
        names.append(entry.name)
    return names


def parse_remote_dir_names(text: str) -> list[str]:
    """Parse the same ``===FILE`` block stream and return run-dir names.

    Mirrors :func:`parse_remote_find_output` but yields ``parts[-2]``
    (the dir name) rather than ``{nnn: ts}``. Malformed paths are
    silently skipped (same robustness contract).
    """
    names: list[str] = []
    blocks = re.split(r'^===FILE ', text, flags=re.MULTILINE)
    for block in blocks:
        if not block.strip():
            continue
        head, _, _rest = block.partition('\n')
        file_path = head.strip()
        parts = file_path.split('/')
        if len(parts) < 3 or parts[0] != 'artifacts' or parts[-1] != 'metadata.toml':
            continue
        if RUN_DIR_RE.match(parts[-2]) is None:
            continue
        names.append(parts[-2])
    return names
