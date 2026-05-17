"""tools/remote infra — paradigm-agnostic ssh/scp helpers for the
Windows GPU box(dev@192.168.31.56 / D:\\gicg_dev)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REMOTE = 'dev@192.168.31.56'
REMOTE_ROOT_WIN = r'D:\gicg_dev'
REMOTE_ROOT_POSIX = '/d/gicg_dev'

DEFAULT_SSH_TIMEOUT = 60


def ssh_run(ps_script: str, timeout: int = DEFAULT_SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet on remote via ssh. stderr decode='replace'(cp936)."""
    cmd = ['ssh', REMOTE, 'powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script]
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)


def scp_to(local: Path, remote_rel: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Local → Windows. `remote_rel` relative to REMOTE_ROOT_POSIX."""
    dst = f'{REMOTE}:{REMOTE_ROOT_POSIX}/{remote_rel}'
    return subprocess.run(
        ['scp', '-q', str(local), dst], capture_output=True, text=True, errors='replace', timeout=timeout
    )


def scp_from(remote_rel: str, local: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    """Windows → Local."""
    src = f'{REMOTE}:{REMOTE_ROOT_POSIX}/{remote_rel}'
    return subprocess.run(
        ['scp', '-q', src, str(local)], capture_output=True, text=True, errors='replace', timeout=timeout
    )


def ps_quote(s: str) -> str:
    """Single-quote for PowerShell。"""
    return "'" + s.replace("'", "''") + "'"
