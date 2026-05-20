"""tools/remote infra — paradigm-agnostic ssh/scp helpers for the
remote GPU host. Host + paths come from ``tools/remote/config.toml``
with env-var override(``GICG_REMOTE_HOST`` / ``GICG_REMOTE_ROOT_WIN``
/ ``GICG_REMOTE_ROOT_POSIX``)+ hardcoded fallback for safety."""

from __future__ import annotations

import base64
import os
import subprocess
import tomllib
from pathlib import Path

_DEFAULTS = {
    'host': 'dev@192.168.31.56',
    'root_win': r'D:\gicg_dev',
    # scp 远端路径用 `D:/` 前缀 — Windows OpenSSH scp 不识别 MSYS 风格
    # `/d/`(`scp: failed to upload file ... to /d/gicg_dev/...`),用
    # drive-letter + forward slash 才 OK。ssh shell 接受 `D:\\` 或 `D:/`。
    'root_posix': 'D:/gicg_dev',
    'gcc_path': r'C:\Strawberry\c\bin',
}


def _load_config() -> dict:
    """Read `tools/remote/config.toml` + apply env-var overrides.
    Missing config file or keys → fall back to ``_DEFAULTS``."""
    cfg_path = Path(__file__).parent / 'config.toml'
    cfg = dict(_DEFAULTS)
    if cfg_path.exists():
        with cfg_path.open('rb') as f:
            file_cfg = tomllib.load(f).get('remote', {})
        cfg.update({k: file_cfg[k] for k in _DEFAULTS if k in file_cfg})
    cfg['host'] = os.environ.get('GICG_REMOTE_HOST', cfg['host'])
    cfg['root_win'] = os.environ.get('GICG_REMOTE_ROOT_WIN', cfg['root_win'])
    cfg['root_posix'] = os.environ.get('GICG_REMOTE_ROOT_POSIX', cfg['root_posix'])
    cfg['gcc_path'] = os.environ.get('GICG_REMOTE_GCC_PATH', cfg['gcc_path'])
    return cfg


_CONFIG = _load_config()
REMOTE = _CONFIG['host']
REMOTE_ROOT_WIN = _CONFIG['root_win']
REMOTE_ROOT_POSIX = _CONFIG['root_posix']
REMOTE_GCC_PATH = _CONFIG['gcc_path']

DEFAULT_SSH_TIMEOUT = 60


def ssh_encoded_argv(ps_script: str) -> list[str]:
    """ssh argv that runs PS via ``-EncodedCommand`` (base64 UTF-16-LE).
    Bypasses Win OpenSSH cmd.exe wrapper which otherwise eats PS ``|`` /
    ``>`` / ``&`` as cmd metacharacters. ``-OutputFormat Text`` + 注入
    ``$ProgressPreference='SilentlyContinue'`` 消 CLIXML serialize 与 PS
    startup ``Preparing modules`` progress noise。"""
    wrapped = "$ProgressPreference='SilentlyContinue'; " + ps_script
    encoded = base64.b64encode(wrapped.encode('utf-16-le')).decode('ascii')
    return [
        'ssh',
        REMOTE,
        'powershell',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-OutputFormat',
        'Text',
        '-EncodedCommand',
        encoded,
    ]


def ssh_run(ps_script: str, timeout: int = DEFAULT_SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet on remote via ssh. stderr decode='replace'(cp936)."""
    return subprocess.run(
        ssh_encoded_argv(ps_script), capture_output=True, text=True, errors='replace', timeout=timeout
    )


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
