"""Kill remote python processes on Windows GPU box via ssh.

Replaces手动 `ssh ... Stop-Process -Name python -Force`。三选一模式:
--all 杀所有 python.exe / --pid <N> 单 PID / --match <substr> 进程名子串。
--dry-run 只列待杀进程不执行。
"""

from __future__ import annotations

import argparse
import sys

from tools.remote._common import ps_quote, ssh_run


def _build_ps(args: argparse.Namespace) -> str:
    """Generate PowerShell snippet per mode + dry-run flag.

    使用 ``$ErrorActionPreference='SilentlyContinue'`` + 末尾 ``exit 0``,让空匹配
    不变成 exit 1(Get-Process 找不到时全局 ``$?=false``,默认 exit code 反映此 state)。
    """
    prelude = "$ErrorActionPreference='SilentlyContinue'; "
    epilogue = '; exit 0'
    if args.all:
        body = (
            'Get-Process python | Format-Table Id,ProcessName,CPU,WS | Out-String'
            if args.dry_run
            else (
                'Get-Process python | Stop-Process -Force; '
                '$c=(Get-Process python | Measure-Object).Count; '
                'Write-Host "remaining python procs: $c"'
            )
        )
        return f'{prelude}{body}{epilogue}'
    if args.pid is not None:
        n = args.pid
        if args.dry_run:
            return (
                f"$ErrorActionPreference='SilentlyContinue'; "
                f'$p = Get-Process -Id {n}; '
                f'if ($p) {{ $p | Format-Table Id,ProcessName,CPU,WS | Out-String; exit 0 }} '
                f'else {{ Write-Host "PID {n} not found"; exit 1 }}'
            )
        return f'try {{ Stop-Process -Id {n} -Force -ErrorAction Stop; exit 0 }} catch {{ Write-Host $_; exit 1 }}'
    pat = ps_quote(f'*{args.match}*')
    sel = f'Get-Process | Where-Object {{ $_.ProcessName -like {pat} }}'
    if args.dry_run:
        body = f'{sel} | Format-Table Id,ProcessName,CPU,WS | Out-String'
    else:
        body = (
            f'{sel} | Stop-Process -Force; $c=({sel} | Measure-Object).Count; Write-Host "remaining matching procs: $c"'
        )
    return f'{prelude}{body}{epilogue}'


def _build_parser() -> argparse.ArgumentParser:
    """argparse with mutex group(--all / --pid / --match)."""
    p = argparse.ArgumentParser(description='Kill remote python processes via ssh.')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--all', action='store_true', help='kill all python.exe')
    g.add_argument('--pid', type=int, help='kill a single PID')
    g.add_argument('--match', type=str, help='kill processes whose name contains substring')
    p.add_argument('--dry-run', action='store_true', help='list targets without killing')
    p.add_argument('--timeout', type=int, default=30, help='ssh timeout seconds, default 30')
    return p


def main() -> int:
    """Parse args → build PS → ssh_run → forward stdout/stderr + returncode."""
    args = _build_parser().parse_args()
    ps = _build_ps(args)
    tag = 'dry-run' if args.dry_run else 'kill'
    print(f'[remote.kill] ({tag}) >> {ps}')
    r = ssh_run(ps, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
