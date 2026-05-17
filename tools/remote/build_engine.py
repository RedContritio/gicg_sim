"""Build libgicg.dll on Windows GPU box (cgo c-shared). CGO_ENABLED=1 +
CC=gcc (MSYS) + PATH 含 MSYS bin. Output -> D:\\gicg_dev\\gicg_env\\libgicg.dll.

Usage::

    .venv/bin/python -m tools.remote.build_engine
"""

from __future__ import annotations

import sys

from tools.remote._common import REMOTE_ROOT_WIN, ssh_run

PS = (
    '$env:CGO_ENABLED=1; $env:CC="gcc"; '
    '$env:PATH="C:\\msys64\\mingw64\\bin;" + $env:PATH; '
    f'cd "{REMOTE_ROOT_WIN}"; '
    'go build -buildmode=c-shared -o gicg_env\\libgicg.dll .\\gicg_engine\\capi\\'
)


def main():
    print('[build_engine] cgo build libgicg.dll on Windows...')
    r = ssh_run(PS, timeout=300)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
