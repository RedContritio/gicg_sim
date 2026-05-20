"""Run a Python module on Windows GPU box via ssh.

Usage::

    .venv/bin/python -m tools.remote.run -- python -m tools.dmc_train configs/dmc_stage3_pilot.toml

`--` 分割 wrapper 参数与远程命令。PS prelude 设 OMP/MKL/PYTHONIOENCODING/PYTHONUNBUFFERED。

Modes:
    default     capture_output=True;命令结束后统一 print stdout/stderr。短命令用。
    --stream    Popen + 逐行实时打到 local stdout/stderr。长跑训练用,避免零反馈。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from typing import IO

from tools.remote._common import REMOTE, REMOTE_ROOT_WIN, ps_quote, ssh_encoded_argv, ssh_run


def _build_ps(cmd_tokens: list[str], cwd: str) -> tuple[str, str]:
    """Return (ps_script, raw_cmd_for_logging)."""
    raw = ' '.join(c for c in cmd_tokens if c != '--')
    ps = (
        '$env:OMP_NUM_THREADS=1; $env:MKL_NUM_THREADS=1; '
        "$env:PYTHONIOENCODING='utf-8'; $env:PYTHONUNBUFFERED=1; "
        f'cd {ps_quote(cwd)}; {raw}'
    )
    return ps, raw


def _pump(stream: IO[str], sink: IO[str]) -> None:
    """Forward each line from a child stream to a local sink. Decoded
    upstream via text=True; encoding errors replaced."""
    for line in iter(stream.readline, ''):
        sink.write(line)
        sink.flush()
    stream.close()


def _run_stream(ps_script: str, timeout: int) -> int:
    """Popen ssh + line-buffer pump stdout/stderr to local. timeout is
    wall-clock; on expiry SIGTERM the child."""
    cmd = ssh_encoded_argv(ps_script)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace', bufsize=1)
    t_out = threading.Thread(target=_pump, args=(proc.stdout, sys.stdout), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, sys.stderr), daemon=True)
    t_out.start()
    t_err.start()
    deadline = time.monotonic() + timeout
    while True:
        rc = proc.poll()
        if rc is not None:
            break
        if time.monotonic() > deadline:
            sys.stderr.write(f'[remote.run] timeout after {timeout}s — SIGTERM\n')
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            rc = proc.returncode if proc.returncode is not None else 124
            break
        time.sleep(0.1)
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    return rc


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cwd', default=REMOTE_ROOT_WIN)
    p.add_argument('--timeout', type=int, default=86400, help='wall-clock seconds, default 1 day')
    p.add_argument('--stream', action='store_true', help='real-time stdout/stderr stream (long-running)')
    p.add_argument('cmd', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if not args.cmd:
        p.error('no command given (use -- to separate)')
    # Join cmd tokens without quoting — PowerShell parses a quoted first
    # token as a literal string expression rather than a command name,
    # and `& 'python'` from Windows ssh server hits an additional cmd.exe
    # quote-doubling pass that breaks the invocation. Tokens with spaces
    # are unsupported (our cwd / module / config paths have none).
    #
    # Use single quotes for env var values — Windows OpenSSH server's
    # cmd.exe wrapper strips unescaped double quotes during argv → shell
    # command join, so `$env:X="v"` arrives as `$env:X=v` (PS then tries
    # to invoke `v` as a command and errors out).
    ps, raw = _build_ps(args.cmd, args.cwd)
    print(f'[remote.run] {REMOTE} >> {raw}' + ('  (stream)' if args.stream else ''))
    if args.stream:
        return _run_stream(ps, timeout=args.timeout)
    r = ssh_run(ps, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
