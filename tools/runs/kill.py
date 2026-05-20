"""Kill remote python processes via ssh — cfg-driven dispatch。

CLI:

    .venv/bin/python -m tools.runs.kill <cfg.toml> --all [--dry-run]
    .venv/bin/python -m tools.runs.kill <cfg.toml> --pid 1234
    .venv/bin/python -m tools.runs.kill <cfg.toml> --match foo

cfg ``[meta].host`` decides local vs remote dispatch。Three mutually-
exclusive modes(``--all`` / ``--pid <N>`` / ``--match <substr>``)+ optional
``--dry-run``。

Local mode currently only supports POSIX(`pgrep` / `kill`); on remote
Windows it shells out via PowerShell ``Get-Process`` / ``Stop-Process``。
"""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
from pathlib import Path

from tools.runs._host import is_local_host, load_remote_from_cfg, ps_quote, ssh_run


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
    """argparse with cfg positional + mutex group(--all / --pid / --match)."""
    p = argparse.ArgumentParser(description='Kill python processes via cfg-driven local/ssh dispatch.')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--all', action='store_true', help='kill all python.exe')
    g.add_argument('--pid', type=int, help='kill a single PID')
    g.add_argument('--match', type=str, help='kill processes whose name contains substring')
    p.add_argument('--dry-run', action='store_true', help='list targets without killing')
    p.add_argument('--timeout', type=int, default=30, help='ssh timeout seconds, default 30')
    return p


def _local_pids_matching(args: argparse.Namespace) -> list[int]:
    """Return PID list for the chosen mode(POSIX local)。"""
    if args.pid is not None:
        return [args.pid]
    pattern = 'python' if args.all else args.match
    r = subprocess.run(['pgrep', '-f', pattern], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def _run_local(args: argparse.Namespace) -> int:
    """Local POSIX dispatch — ``pgrep`` enumerate + ``kill`` send SIGTERM。
    Windows local not supported(use cfg with [remote].hostname=match for
    in-box workflow)。"""
    if sys.platform == 'win32':
        sys.stderr.write(
            'error: local Windows kill not implemented; on Windows GPU box, run with cfg whose [remote].hostname matches socket.gethostname().\n'
        )
        return 2
    pids = _local_pids_matching(args)
    tag = 'dry-run' if args.dry_run else 'kill'
    print(f'[local.kill] ({tag}) matched {len(pids)} pid(s): {pids}')
    if args.dry_run or not pids:
        return 0
    rc = 0
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError as e:
            sys.stderr.write(f'[local.kill] pid {pid}: {e}\n')
            rc = 1
    return rc


def _run_remote(remote, args: argparse.Namespace) -> int:
    """Remote ssh dispatch — send PS body directly(not python -m self,which
    would recurse)。"""
    ps = _build_ps(args)
    tag = 'dry-run' if args.dry_run else 'kill'
    print(f'[remote.kill] ({tag}) {remote.ssh} >> {ps}')
    r = ssh_run(remote, ps, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def main() -> int:
    """Parse args → load cfg → local-or-remote dispatch。"""
    args = _build_parser().parse_args()
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None
    return _run_remote(remote, args)


if __name__ == '__main__':
    sys.exit(main())
