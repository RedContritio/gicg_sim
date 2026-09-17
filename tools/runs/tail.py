"""Tail a local file or a file on a remote host.

CLI:

    .venv/bin/python -m tools.runs.tail <cfg.toml> <path> [--lines N --follow]

The remote path uses PowerShell on Windows and POSIX ``tail`` elsewhere.

Drive-letter / absolute prefix on ``path`` → use as-is;else relative to
``[remote].root``(remote)or current dir(local)。
"""

from __future__ import annotations

import argparse
import shlex
import sys
from pathlib import Path
from subprocess import TimeoutExpired

from tools.runs._host import (
    RemoteCfg,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    run_argv,
    ssh_bash_argv,
    ssh_encoded_argv,
    ssh_run,
    ssh_run_bash,
    stream_argv,
)


def _normalize_remote_path(remote: RemoteCfg, path: str) -> str:
    """Drive-letter prefix → absolute path; else relative to ``remote.root``。"""
    if len(path) >= 2 and path[1] == ':' and path[0].isalpha():
        return path
    if path.startswith('/'):
        return path
    return f'{remote.root}/{path}'


def _build_ps(path: str, lines: int, follow: bool) -> str:
    """PS Get-Content w/ -Tail (+ -Wait when following), forced UTF8."""
    wait = ' -Wait' if follow else ''
    return f'Get-Content -Path {ps_quote(path)} -Tail {lines}{wait} -Encoding UTF8'


def _build_sh(path: str, lines: int, follow: bool) -> str:
    """POSIX tail with only the requested number of lines."""
    wait = ' -F' if follow else ''
    return f'tail -n {lines}{wait} -- {shlex.quote(path)}'


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='tools.runs.tail')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument('path', help='file path (relative to [remote].root, or absolute D:\\... / /abs)')
    p.add_argument('--lines', type=int, default=20)
    p.add_argument('--follow', action='store_true', help='stream new lines (-Wait / tail -F)')
    p.add_argument('--timeout', type=int, default=None, help='ssh wall-clock seconds')
    return p


def _run_follow_argv(argv: list[str], timeout: int) -> int:
    return stream_argv(argv, timeout=timeout, label='[tail]')


def _run_local(args: argparse.Namespace) -> int:
    """POSIX tail -n / tail -F。"""
    if args.follow:
        argv = ['tail', '-n', str(args.lines), '-F', args.path]
        return _run_follow_argv(argv, timeout=args.timeout if args.timeout is not None else 86400)
    argv = ['tail', '-n', str(args.lines), args.path]
    try:
        r = run_argv(argv, timeout=args.timeout if args.timeout is not None else 30)
        return r.returncode
    except TimeoutExpired:
        return 124


def _run_remote(remote: RemoteCfg, args: argparse.Namespace) -> int:
    path = _normalize_remote_path(remote, args.path)
    if remote.os == 'windows':
        script = _build_ps(path, args.lines, args.follow)
        argv = ssh_encoded_argv(remote, script)
    else:
        script = _build_sh(path, args.lines, args.follow)
        argv = ssh_bash_argv(remote, script)
    if args.follow:
        return _run_follow_argv(argv, timeout=args.timeout if args.timeout is not None else 86400)
    if remote.os == 'windows':
        r = ssh_run(remote, script, timeout=args.timeout if args.timeout is not None else 30)
    else:
        r = ssh_run_bash(remote, script, timeout=args.timeout if args.timeout is not None else 30)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.returncode != 0 and r.stderr and ('Cannot find path' in r.stderr or 'No such file or directory' in r.stderr):
        sys.stderr.write(f'[tail] remote file not found: {path}\n')
        return 1
    if r.stderr:
        sys.stderr.write(r.stderr)
    return 1 if r.returncode != 0 else 0


def main() -> int:
    args = _build_parser().parse_args()
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None
    return _run_remote(remote, args)


if __name__ == '__main__':
    sys.exit(main())
