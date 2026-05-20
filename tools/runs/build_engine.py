"""Build libgicg.dll on remote box via cgo c-shared — cfg-driven dispatch。

CLI:

    .venv/bin/python -m tools.runs.build_engine <cfg.toml>

Probes ``go`` + ``gcc`` on the remote PATH(``discover_remote_binary``);
both must already be installed + on PATH。 ``gcc`` path is no longer
prepended — that's a deploy-side concern。

Output:
  - Windows  → ``<remote.root>\\gicg_env\\libgicg.dll``
  - POSIX    → ``<remote.root>/gicg_env/libgicg.so``
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.runs._host import (
    RemoteCfg,
    discover_remote_binary,
    is_local_host,
    load_remote_from_cfg,
    ssh_run,
    ssh_run_bash,
)


def _build_ps_windows(remote: RemoteCfg) -> str:
    """Single-quote env var value — Win OpenSSH cmd.exe wrapper strips
    unescaped double quotes(同 ``_ssh.py`` 注释)。"""
    return (
        "$env:CGO_ENABLED=1; $env:CC='gcc'; "
        f'cd "{remote.root_native}"; '
        'go build -buildmode=c-shared -o gicg_env\\libgicg.dll .\\gicg_engine\\capi\\'
    )


def _build_sh_posix(remote: RemoteCfg) -> str:
    return f'cd {remote.root} && CGO_ENABLED=1 go build -buildmode=c-shared -o gicg_env/libgicg.so ./gicg_engine/capi/'


def _run_remote(remote: RemoteCfg, timeout: int) -> int:
    # Probe-first — fail loud + actionable if go or gcc absent。
    discover_remote_binary(remote, 'go')
    if remote.os == 'windows':
        discover_remote_binary(remote, 'gcc')
        ps = _build_ps_windows(remote)
        print(f'[build_engine] {remote.ssh} (windows) >> {ps}')
        r = ssh_run(remote, ps, timeout=timeout)
    else:
        discover_remote_binary(remote, 'gcc')
        sh = _build_sh_posix(remote)
        print(f'[build_engine] {remote.ssh} ({remote.os}) >> {sh}')
        r = ssh_run_bash(remote, sh, timeout=timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def _run_local(args) -> int:
    """Local — defer to user's normal build command(makes no sense to
    re-implement here)。"""
    sys.stderr.write(
        '[build_engine] cfg [meta].host=local (or loopback); '
        'use `go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/` directly.\n'
    )
    return 1


def main():
    p = argparse.ArgumentParser(description='cgo build libgicg shared lib on the cfg-selected host.')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument('--timeout', type=int, default=300, help='ssh wall-clock seconds, default 300')
    args = p.parse_args()
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None
    return _run_remote(remote, timeout=args.timeout)


if __name__ == '__main__':
    sys.exit(main())
