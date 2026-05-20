"""Tail a remote file via cfg-driven local/ssh dispatch。

CLI:

    .venv/bin/python -m tools.runs.tail <cfg.toml> <path> [--lines N --follow]

cfg ``[meta].host`` decides local vs remote。On remote Windows the
remote read goes via PowerShell ``Get-Content -Tail N``(+ ``-Wait`` when
``--follow``)。Local mode uses POSIX ``tail``。

Drive-letter / absolute prefix on ``path`` → use as-is;else relative to
``[remote].root``(remote)or current dir(local)。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

from tools.runs._host import RemoteCfg, is_local_host, load_remote_from_cfg, ps_quote, ssh_encoded_argv, ssh_run


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


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='tools.runs.tail')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument('path', help='file path (relative to [remote].root, or absolute D:\\... / /abs)')
    p.add_argument('--lines', type=int, default=20)
    p.add_argument('--follow', action='store_true', help='stream new lines (-Wait / tail -F)')
    p.add_argument('--timeout', type=int, default=None, help='ssh wall-clock seconds')
    return p


def _pump(stream: IO[str], sink: IO[str]) -> None:
    for line in iter(stream.readline, ''):
        sink.write(line)
        sink.flush()
    stream.close()


def _shutdown(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()


def _run_follow_argv(argv: list[str], timeout: int) -> int:
    """Popen + pump stdout/stderr; SIGINT → 130; timeout → 124。"""
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace', bufsize=1
    )
    t_out = threading.Thread(target=_pump, args=(proc.stdout, sys.stdout), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, sys.stderr), daemon=True)
    t_out.start()
    t_err.start()
    deadline = time.monotonic() + timeout
    rc: int
    try:
        while (rc := proc.poll()) is None:
            if time.monotonic() > deadline:
                sys.stderr.write(f'[tail] timeout after {timeout}s — SIGTERM\n')
                _shutdown(proc)
                rc = 124
                break
            time.sleep(0.1)
    except KeyboardInterrupt:
        _shutdown(proc)
        rc = 130
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    return rc


def _run_local(args: argparse.Namespace) -> int:
    """POSIX tail -n / tail -F。"""
    if args.follow:
        argv = ['tail', '-n', str(args.lines), '-F', args.path]
        return _run_follow_argv(argv, timeout=args.timeout if args.timeout is not None else 86400)
    argv = ['tail', '-n', str(args.lines), args.path]
    try:
        r = subprocess.run(argv, timeout=args.timeout if args.timeout is not None else 30)
        return r.returncode
    except subprocess.TimeoutExpired:
        return 124


def _run_remote(remote: RemoteCfg, args: argparse.Namespace) -> int:
    path = _normalize_remote_path(remote, args.path)
    ps = _build_ps(path, args.lines, args.follow)
    if args.follow:
        return _run_follow_argv(
            ssh_encoded_argv(remote, ps), timeout=args.timeout if args.timeout is not None else 86400
        )
    r = ssh_run(remote, ps, timeout=args.timeout if args.timeout is not None else 30)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.returncode != 0 and r.stderr and 'Cannot find path' in r.stderr:
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
