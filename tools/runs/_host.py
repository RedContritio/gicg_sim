"""Cfg-driven SSH host resolution and remote transport.

Training cfg selects a profile under ``[remote]``; host values live in the
gitignored ``configs/hosts/hosts.toml`` registry. Remote binary locations are
probed rather than configured.
"""

from __future__ import annotations

import base64
import shlex
import socket
import subprocess
import sys
import threading
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Literal

VENV_DIRS = ['.venv', 'venv', 'env', '.virtualenv']
DEFAULT_SSH_TIMEOUT = 60
HOST_REGISTRY = Path(__file__).resolve().parents[2] / 'configs' / 'hosts' / 'hosts.toml'


@dataclass(frozen=True)
class RemoteCfg:
    """Validated remote endpoint selected by a cfg host profile."""

    ssh: str
    root: str  # forward-slash form, e.g. 'D:/gicg_dev'
    os: Literal['windows', 'linux', 'darwin']
    hostname: str

    @property
    def root_native(self) -> str:
        """Native-OS path string — Windows backslashes for cd / tar args
        in PowerShell, POSIX otherwise."""
        return self.root.replace('/', '\\') if self.os == 'windows' else self.root


def _registry_entry(profile: str, raw: dict, path: Path) -> RemoteCfg:
    required = ['ssh', 'root', 'os', 'hostname']
    missing = [key for key in required if key not in raw]
    if missing:
        raise ValueError(f'host registry profile {profile!r} missing required fields {missing} in {path}')
    if raw['os'] not in ('windows', 'linux', 'darwin'):
        raise ValueError(
            f'host registry profile {profile!r} os must be windows/linux/darwin, got {raw["os"]!r} in {path}'
        )
    if not str(raw['ssh']).strip():
        raise ValueError(f'host registry profile {profile!r} ssh must be non-empty in {path}')
    if not str(raw['hostname']).strip():
        raise ValueError(f'host registry profile {profile!r} hostname must be non-empty in {path}')
    root = str(raw['root'])
    if not root.strip():
        raise ValueError(f'host registry profile {profile!r} root must be non-empty in {path}')
    if '/' in root and '\\' in root:
        raise ValueError(
            f'host registry profile {profile!r} root must use forward slashes only, got mixed: {root!r} in {path}'
        )
    if '/' not in root and '\\' in root:
        raise ValueError(
            f'host registry profile {profile!r} root must use forward slashes (got {root!r}); '
            "Windows scp needs drive-letter + '/'."
        )
    return RemoteCfg(ssh=str(raw['ssh']), root=root, os=str(raw['os']), hostname=str(raw['hostname']))


def load_host_registry(path: Path) -> dict[str, RemoteCfg]:
    """Read and validate every profile in a host registry."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(
            f'host registry not found: {path}; create it with '
            f'`cp configs/hosts/hosts.example.toml configs/hosts/hosts.toml`'
        )
    raw = tomllib.loads(path.read_text(encoding='utf-8'))
    profiles: dict[str, RemoteCfg] = {}
    for profile, entry in raw.items():
        if not isinstance(entry, dict):
            raise ValueError(f'host registry profile {profile!r} must be a TOML table in {path}')
        profiles[profile] = _registry_entry(profile, entry, path)
    return profiles


def load_remote_from_cfg(cfg_path: Path, registry_path: Path | None = None) -> RemoteCfg | None:
    """Read cfg.toml and resolve its remote profile. ``meta.host == 'local'``
    (or missing) returns None; remote configs require a valid registry entry."""
    # encoding='utf-8' 显式 — Win 默认 GBK,cfg toml 含 非 ASCII (中文 char_name 等)
    # 或 UTF-8 BOM 时 read_text() 默认 codec UnicodeDecodeError fail-loud。
    cfg = tomllib.loads(Path(cfg_path).read_text(encoding='utf-8'))
    meta = cfg.get('meta', {})
    host = meta.get('host', 'local')
    if host not in ('local', 'remote'):
        raise ValueError(f"cfg [meta].host must be 'local' or 'remote', got {host!r} in {cfg_path}")
    if host == 'local':
        return None
    if 'remote' not in cfg:
        raise ValueError(f"cfg [meta].host='remote' but [remote] section missing in {cfg_path}")
    profile = cfg['remote'].get('profile')
    if not isinstance(profile, str) or not profile.strip():
        raise ValueError(f'cfg [remote].profile must be non-empty in {cfg_path}')
    registry = Path(registry_path) if registry_path is not None else HOST_REGISTRY
    profiles = load_host_registry(registry)
    if profile not in profiles:
        available = ', '.join(sorted(profiles)) or '<none>'
        raise ValueError(f'host profile {profile!r} not found in {registry}; available: {available}')
    return profiles[profile]


def is_local_host(remote: RemoteCfg | None) -> bool:
    """No remote cfg, or we're physically on the remote box(hostname
    match,case-insensitive — Windows gethostname() 常返大写,cfg 可能小写)。"""
    if remote is None:
        return True
    return socket.gethostname().lower() == remote.hostname.lower()


def ssh_encoded_argv(remote: RemoteCfg, ps_script: str) -> list[str]:
    """Run PowerShell through ssh without cmd.exe metacharacter parsing."""
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


def ssh_bash_argv(remote: RemoteCfg, bash_script: str) -> list[str]:
    """ssh argv that runs a bash snippet on a POSIX remote。"""
    return ['ssh', remote.ssh, f'bash -c {shlex.quote(bash_script)}']


def _pump(stream: IO[str], sink: IO[str]) -> None:
    for line in iter(stream.readline, ''):
        sink.write(line)
        sink.flush()
    stream.close()


def _shutdown(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def run_argv(argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run argv with inherited stdio."""
    return subprocess.run(argv, timeout=timeout)


def run_argv_capture(argv: list[str], timeout: float | None = None) -> subprocess.CompletedProcess:
    """Run argv with text stdout/stderr captured and decode errors replaced."""
    return subprocess.run(
        argv,
        capture_output=True,
        text=True,
        errors='replace',
        timeout=timeout,
    )


def stream_argv(argv: list[str], *, timeout: float | None, label: str) -> int:
    """Run argv with realtime stdout/stderr forwarding."""
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace', bufsize=1
    )
    t_out = threading.Thread(target=_pump, args=(proc.stdout, sys.stdout), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, sys.stderr), daemon=True)
    t_out.start()
    t_err.start()
    deadline = time.monotonic() + timeout if timeout is not None else None
    rc: int
    try:
        while (rc := proc.poll()) is None:
            if deadline is not None and time.monotonic() > deadline:
                sys.stderr.write(f'{label} timeout after {timeout}s — SIGTERM\n')
                _shutdown(proc)
                rc = 124
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        sys.stderr.write(f'{label} SIGINT — terminating child proc\n')
        _shutdown(proc)
        rc = 130
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    return rc


def ssh_run(remote: RemoteCfg, ps_script: str, timeout: int = DEFAULT_SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet on remote via ssh. stderr decode='replace'(cp936)."""
    return run_argv_capture(ssh_encoded_argv(remote, ps_script), timeout=timeout)


def ssh_run_bash(
    remote: RemoteCfg, bash_script: str, timeout: int = DEFAULT_SSH_TIMEOUT
) -> subprocess.CompletedProcess:
    """Run a bash one-liner on a POSIX remote(linux/darwin)。"""
    return run_argv_capture(ssh_bash_argv(remote, bash_script), timeout=timeout)


def scp_to(remote: RemoteCfg, local: Path, remote_rel: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Local → remote. ``remote_rel`` is relative to ``remote.root``。"""
    dst = f'{remote.ssh}:{remote.root}/{remote_rel}'
    return run_argv_capture(['scp', '-q', str(local), dst], timeout=timeout)


def scp_from(
    remote: RemoteCfg,
    remote_rel: str,
    local: Path,
    timeout: int = 120,
    *,
    preserve: bool = False,
) -> subprocess.CompletedProcess:
    """Remote → local."""
    src = f'{remote.ssh}:{remote.root}/{remote_rel}'
    flags = ['-q']
    if preserve:
        flags.append('-p')
    return run_argv_capture(['scp', *flags, src, str(local)], timeout=timeout)


def rsync_run(argv: list[str], timeout: int = 300) -> subprocess.CompletedProcess:
    """Execute an rsync argv built by the sync layer."""
    return run_argv_capture(argv, timeout=timeout)


def ps_quote(s: str) -> str:
    """Single-quote for PowerShell。"""
    return "'" + s.replace("'", "''") + "'"


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
        chain = ' || '.join(f'([ -x {shlex.quote(c)} ] && printf "%s\\n" {shlex.quote(c)})' for c in candidates)
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
        r = ssh_run_bash(remote, f'command -v {shlex.quote(name)} || true')
        found = (r.stdout or '').strip()
    if not found:
        hint = (
            'add to System Environment Variables → PATH and reopen ssh session'
            if remote.os == 'windows'
            else 'install or fix $PATH'
        )
        raise FileNotFoundError(f'`{name}` not in PATH on {remote.ssh}. {hint}.')
    return found
