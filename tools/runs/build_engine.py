"""Build libgicg.dll on Windows GPU box (cgo c-shared). CGO_ENABLED=1 +
CC=gcc (Strawberry Perl ships gcc) + PATH 含 gcc bin. Output ->
<REMOTE_ROOT_WIN>\\gicg_env\\libgicg.dll.

Usage::

    .venv/bin/python -m tools.runs.build_engine
"""

from __future__ import annotations

import sys

from tools.runs._host import REMOTE_GCC_PATH, REMOTE_ROOT_WIN, ssh_run

# single-quote 包 env var value — Windows OpenSSH 的 cmd.exe wrapper 会 strip
# 未 escape 的 double quote(同 tools/runs/_ssh.py line 91-94)。
PS = (
    "$env:CGO_ENABLED=1; $env:CC='gcc'; "
    f"$env:PATH='{REMOTE_GCC_PATH};' + $env:PATH; "
    f'cd "{REMOTE_ROOT_WIN}"; '
    'gcc --version 2>$null; '
    f'if ($LASTEXITCODE -ne 0) {{ Write-Error "gcc not found at {REMOTE_GCC_PATH}, override via GICG_REMOTE_GCC_PATH env var"; exit 1 }}; '
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
