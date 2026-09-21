"""Content manifest helpers for remote source synchronization."""

from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from pathlib import Path

from tools.runs._host import RemoteCfg, ps_quote, scp_to, ssh_run, ssh_run_bash

MANIFEST_FILE = '.sync_manifest.json'


def hash_file(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def read_remote_manifest(remote: RemoteCfg) -> dict[str, str]:
    if remote.os == 'windows':
        ps = (
            f'$p = Join-Path {ps_quote(remote.root_native)} {ps_quote(MANIFEST_FILE)}; '
            f'if (Test-Path $p) {{ Get-Content -Raw $p }} else {{ "" }}'
        )
        result = ssh_run(remote, ps)
    else:
        sh = (
            f'cd {shlex_quote(remote.root)} && '
            f'if [ -f {shlex_quote(MANIFEST_FILE)} ]; then cat {shlex_quote(MANIFEST_FILE)}; fi'
        )
        result = ssh_run_bash(remote, sh)
    if result.returncode != 0 or not (result.stdout or '').strip():
        return {}
    try:
        data = json.loads(result.stdout)
        return {str(key): str(value) for key, value in data.items()}
    except (ValueError, AttributeError):
        print('[sync] WARN: remote manifest unreadable — treating as empty (full push)', file=sys.stderr)
        return {}


def write_remote_manifest(remote: RemoteCfg, manifest: dict[str, str]) -> int:
    with tempfile.NamedTemporaryFile('w', suffix='.json', delete=False) as handle:
        json.dump(manifest, handle, sort_keys=True)
        local = Path(handle.name)
    try:
        return scp_to(remote, local, MANIFEST_FILE).returncode
    finally:
        local.unlink(missing_ok=True)


def shlex_quote(value: str) -> str:
    import shlex

    return shlex.quote(value)
