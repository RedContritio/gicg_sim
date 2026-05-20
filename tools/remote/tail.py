"""Tail a remote file on the Windows GPU box via ssh + PS Get-Content.
Non-follow = one-shot ``-Tail N``;``--follow`` = ``-Wait`` stream until
SIGINT / wall-clock timeout. Drive-letter prefix → absolute Win path;
else relative to ``REMOTE_ROOT_POSIX``."""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from typing import IO

from tools.remote._common import REMOTE_ROOT_POSIX, ps_quote, ssh_encoded_argv, ssh_run


def _normalize_path(path: str) -> str:
    """Drive-letter prefix → absolute Win path; else relative to root."""
    if len(path) >= 2 and path[1] == ':' and path[0].isalpha():
        return path
    return f'{REMOTE_ROOT_POSIX}/{path}'


def _build_ps(path: str, lines: int, follow: bool) -> str:
    """PS Get-Content w/ -Tail (+ -Wait when following), forced UTF8."""
    wait = ' -Wait' if follow else ''
    return f'Get-Content -Path {ps_quote(path)} -Tail {lines}{wait} -Encoding UTF8'


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='tools.remote.tail')
    p.add_argument('path', help='remote path (relative to REMOTE_ROOT_POSIX, or absolute D:\\...)')
    p.add_argument('--lines', type=int, default=20)
    p.add_argument('--follow', action='store_true', help='stream new lines (Get-Content -Wait)')
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


def _run_follow(ps: str, timeout: int) -> int:
    """Popen ssh + pump stdout/stderr; SIGINT → 130; timeout → 124."""
    proc = subprocess.Popen(
        ssh_encoded_argv(ps),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors='replace',
        bufsize=1,
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
                sys.stderr.write(f'[remote.tail] timeout after {timeout}s — SIGTERM\n')
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


def main() -> int:
    args = _build_parser().parse_args()
    path = _normalize_path(args.path)
    ps = _build_ps(path, args.lines, args.follow)
    if args.follow:
        return _run_follow(ps, timeout=args.timeout if args.timeout is not None else 86400)
    r = ssh_run(ps, timeout=args.timeout if args.timeout is not None else 30)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.returncode != 0 and r.stderr and 'Cannot find path' in r.stderr:
        sys.stderr.write(f'[remote.tail] remote file not found: {path}\n')
        return 1
    if r.stderr:
        sys.stderr.write(r.stderr)
    return 1 if r.returncode != 0 else 0


if __name__ == '__main__':
    sys.exit(main())
