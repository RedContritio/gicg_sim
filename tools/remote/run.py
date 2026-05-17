"""Run a Python module on Windows GPU box via ssh.

Usage::

    .venv/bin/python -m tools.remote.run -- python -m tools.dmc_train configs/dmc_stage3_pilot.toml

`--` 分割 wrapper 参数与远程命令。PS prelude 设 OMP/MKL/PYTHONIOENCODING/PYTHONUNBUFFERED。"""

from __future__ import annotations

import argparse
import sys

from tools.remote._common import REMOTE, REMOTE_ROOT_WIN, ps_quote, ssh_run


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cwd', default=REMOTE_ROOT_WIN)
    p.add_argument('--timeout', type=int, default=86400, help='default 1 day')
    p.add_argument('cmd', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if not args.cmd:
        p.error('no command given (use -- to separate)')
    raw = ' '.join(ps_quote(c) for c in args.cmd if c != '--')
    ps = (
        '$env:OMP_NUM_THREADS=1; $env:MKL_NUM_THREADS=1; '
        '$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUNBUFFERED=1; '
        f'cd {ps_quote(args.cwd)}; {raw}'
    )
    print(f'[remote.run] {REMOTE} >> {raw}')
    r = ssh_run(ps, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
