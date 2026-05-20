"""tools/runs ssh host infra — cfg-driven RemoteCfg + probe helpers.

每训练 cfg.toml 自闭包含 host 决策:

    [meta]
    host = "local"            # or "remote"
    [remote]                  # required when host == "remote"
    ssh = "dev@192.168.31.56"
    root = "D:/gicg_dev"      # 始终 forward slash;Windows scp drive-letter 兼容
    os = "windows"            # windows | linux | darwin
    hostname = "DEV-PC"       # remote box's socket.gethostname(),用于 loopback detect

工具 main 第一 positional 接 cfg.toml,据 ``[meta].host`` 决定本地跑 / ssh forward
到远端。RemoteCfg 既无 binary path 字段也无 env override — 远端 Python venv / go /
gcc 全 probe(``discover_remote_*``),probe fail loud raise FileNotFoundError。

字段缺失 / 值非法 → ``ValueError``(per CLAUDE.md "意外输入必须抛异常")。
"""

from __future__ import annotations

import base64
import socket
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

VENV_DIRS = ['.venv', 'venv', 'env', '.virtualenv']
DEFAULT_SSH_TIMEOUT = 60


@dataclass(frozen=True)
class RemoteCfg:
    """Validated remote host config extracted from cfg ``[remote]``.

    Fields are exactly what's needed to ssh + know whether we're already
    physically on the remote box(loopback detect via ``hostname``)。
    """

    ssh: str
    root: str  # forward-slash form, e.g. 'D:/gicg_dev'
    os: Literal['windows', 'linux', 'darwin']
    hostname: str

    @property
    def root_native(self) -> str:
        """Native-OS path string — Windows backslashes for cd / tar args
        in PowerShell, POSIX otherwise."""
        return self.root.replace('/', '\\') if self.os == 'windows' else self.root


def load_remote_from_cfg(cfg_path: Path) -> RemoteCfg | None:
    """Read cfg.toml; if ``meta.host == 'remote'`` extract+validate
    ``[remote]`` section + return RemoteCfg。``meta.host == 'local'``(或缺失)
    返回 None。任何 schema 违规直接 raise — no silent fallback。"""
    cfg = tomllib.loads(Path(cfg_path).read_text())
    meta = cfg.get('meta', {})
    host = meta.get('host', 'local')
    if host not in ('local', 'remote'):
        raise ValueError(f"cfg [meta].host must be 'local' or 'remote', got {host!r} in {cfg_path}")
    if host == 'local':
        return None
    if 'remote' not in cfg:
        raise ValueError(f"cfg [meta].host='remote' but [remote] section missing in {cfg_path}")
    r = cfg['remote']
    required = ['ssh', 'root', 'os', 'hostname']
    missing = [k for k in required if k not in r]
    if missing:
        raise ValueError(f'cfg [remote] missing required fields {missing} in {cfg_path}')
    if r['os'] not in ('windows', 'linux', 'darwin'):
        raise ValueError(f'cfg [remote].os must be windows/linux/darwin, got {r["os"]!r} in {cfg_path}')
    if '/' not in r['root'] and '\\' in r['root']:
        raise ValueError(
            f"cfg [remote].root must use forward slashes (got {r['root']!r}); Windows scp needs drive-letter + '/'."
        )
    return RemoteCfg(ssh=str(r['ssh']), root=str(r['root']), os=str(r['os']), hostname=str(r['hostname']))


def is_local_host(remote: RemoteCfg | None) -> bool:
    """No remote cfg, or we're physically on the remote box(hostname
    match,case-insensitive — Windows gethostname() 常返大写,cfg 可能小写)。"""
    if remote is None:
        return True
    return socket.gethostname().lower() == remote.hostname.lower()


# ---------------------------------------------------------------------------
# ssh primitives — now take a RemoteCfg explicitly instead of module globals.
# ---------------------------------------------------------------------------


def ssh_encoded_argv(remote: RemoteCfg, ps_script: str) -> list[str]:
    """ssh argv that runs PS via ``-EncodedCommand``(base64 UTF-16-LE)。
    Bypasses Win OpenSSH cmd.exe wrapper which otherwise eats PS ``|`` /
    ``>`` / ``&`` as cmd metacharacters。``-OutputFormat Text`` + 注入
    ``$ProgressPreference='SilentlyContinue'`` 消 CLIXML serialize 与 PS
    startup ``Preparing modules`` progress noise。"""
    wrapped = "$ProgressPreference='SilentlyContinue'; " + ps_script
    encoded = base64.b64encode(wrapped.encode('utf-16-le')).decode('ascii')
    return [
        'ssh',
        remote.ssh,
        'powershell',
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-OutputFormat',
        'Text',
        '-EncodedCommand',
        encoded,
    ]


def ssh_run(remote: RemoteCfg, ps_script: str, timeout: int = DEFAULT_SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet on remote via ssh. stderr decode='replace'(cp936)."""
    return subprocess.run(
        ssh_encoded_argv(remote, ps_script),
        capture_output=True,
        text=True,
        errors='replace',
        timeout=timeout,
    )


def ssh_run_bash(
    remote: RemoteCfg, bash_script: str, timeout: int = DEFAULT_SSH_TIMEOUT
) -> subprocess.CompletedProcess:
    """Run a bash one-liner on a POSIX remote(linux/darwin)。"""
    return subprocess.run(
        ['ssh', remote.ssh, 'bash', '-c', bash_script],
        capture_output=True,
        text=True,
        errors='replace',
        timeout=timeout,
    )


def scp_to(remote: RemoteCfg, local: Path, remote_rel: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Local → remote. ``remote_rel`` is relative to ``remote.root``。"""
    dst = f'{remote.ssh}:{remote.root}/{remote_rel}'
    return subprocess.run(
        ['scp', '-q', str(local), dst], capture_output=True, text=True, errors='replace', timeout=timeout
    )


def scp_from(remote: RemoteCfg, remote_rel: str, local: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    """Remote → local."""
    src = f'{remote.ssh}:{remote.root}/{remote_rel}'
    return subprocess.run(
        ['scp', '-q', src, str(local)], capture_output=True, text=True, errors='replace', timeout=timeout
    )


def ps_quote(s: str) -> str:
    """Single-quote for PowerShell。"""
    return "'" + s.replace("'", "''") + "'"


# ---------------------------------------------------------------------------
# Remote-side probe helpers — discover python venv interpreter / arbitrary
# binaries(go / gcc)on the remote, raise loudly if missing。
# ---------------------------------------------------------------------------


def _venv_python_candidates(remote: RemoteCfg) -> list[str]:
    if remote.os == 'windows':
        sub = ['Scripts/python.exe', 'Scripts/python3.exe']
    else:
        sub = ['bin/python', 'bin/python3']
    return [f'{remote.root}/{v}/{s}' for v in VENV_DIRS for s in sub]


def discover_remote_python(remote: RemoteCfg) -> str:
    """Probe remote Python interpreter across venv-name × interp-subpath
    grid. Raise FileNotFoundError with a setup hint if nothing exists。"""
    candidates = _venv_python_candidates(remote)
    if remote.os == 'windows':
        paths_arr = '@(' + ','.join(ps_quote(c) for c in candidates) + ')'
        ps = f'$paths = {paths_arr}; ($paths | Where-Object {{ Test-Path $_ }} | Select-Object -First 1)'
        r = ssh_run(remote, ps)
        found = (r.stdout or '').strip()
    else:
        chain = ' || '.join(f'([ -x "{c}" ] && echo "{c}")' for c in candidates)
        r = ssh_run_bash(remote, chain + ' || true')
        found = (r.stdout or '').strip().splitlines()[0] if r.stdout.strip() else ''
    if not found:
        raise FileNotFoundError(
            f'No Python venv found on {remote.ssh}:{remote.root}/. '
            f'Tried venv dirs {VENV_DIRS} × interpreter sub-paths. '
            f'Create one: `cd {remote.root} && python -m venv .venv`.'
        )
    return found


def discover_remote_binary(remote: RemoteCfg, name: str) -> str:
    """``go`` / ``gcc`` / etc — PATH lookup on remote, raise if missing。"""
    if remote.os == 'windows':
        ps = f'(Get-Command {name} -ErrorAction SilentlyContinue).Source'
        r = ssh_run(remote, ps)
        found = (r.stdout or '').strip().splitlines()[0] if r.stdout.strip() else ''
    else:
        r = ssh_run_bash(remote, f'command -v {name} || true')
        found = (r.stdout or '').strip()
    if not found:
        hint = (
            'add to System Environment Variables → PATH and reopen ssh session'
            if remote.os == 'windows'
            else 'install or fix $PATH'
        )
        raise FileNotFoundError(f'`{name}` not in PATH on {remote.ssh}. {hint}.')
    return found
