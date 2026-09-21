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
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path

from tools.runs._host import is_local_host, load_remote_from_cfg, ps_quote, ssh_run, ssh_run_bash

KILL_WAIT_SECONDS = 2.0
KILL_POLL_SECONDS = 0.1


def _build_ps(args: argparse.Namespace) -> str:
    """Generate PowerShell snippet per mode + dry-run flag.

    使用 ``$ErrorActionPreference='SilentlyContinue'`` 让空匹配不变成 exit 1。
    """
    prelude = "$ErrorActionPreference='SilentlyContinue'; "
    if args.all:
        if args.dry_run:
            body = 'Get-Process python -ErrorAction SilentlyContinue | Format-Table Id,ProcessName,CPU,WS | Out-String'
            return f'{prelude}{body}; exit 0'
        body = (
            '$targets=@(Get-Process python -ErrorAction SilentlyContinue); '
            '$failed=$false; '
            'foreach ($p in $targets) { '
            'try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } '
            'catch { Write-Error $_ -ErrorAction Continue; $failed=$true } }; '
            '$remaining=@(Get-Process python -ErrorAction SilentlyContinue); '
            '$c=$remaining.Count; '
            'Write-Host "remaining python procs: $c"; '
            'if ($failed -or $c -gt 0) { exit 1 } else { exit 0 }'
        )
        return f'{prelude}{body}'
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
    sel = f'Get-Process -ErrorAction SilentlyContinue | Where-Object {{ $_.ProcessName -like {pat} }}'
    if args.dry_run:
        body = f'{sel} | Format-Table Id,ProcessName,CPU,WS | Out-String'
    else:
        body = (
            f'$targets=@({sel}); '
            '$failed=$false; '
            'foreach ($p in $targets) { '
            'try { Stop-Process -Id $p.Id -Force -ErrorAction Stop } '
            'catch { Write-Error $_ -ErrorAction Continue; $failed=$true } }; '
            f'$remaining=@({sel}); '
            '$c=$remaining.Count; '
            'Write-Host "remaining matching procs: $c"; '
            'if ($failed -or $c -gt 0) { exit 1 } else { exit 0 }'
        )
    if args.dry_run:
        return f'{prelude}{body}; exit 0'
    return f'{prelude}{body}'


def _posix_rows(pattern: str | None = None) -> str:
    if pattern is None:
        match = 'if (tolower(c) ~ /^python([0-9.]*)?$/)'
    else:
        match = 'if (index(tolower(c), tolower(pat)) > 0)'
    script = f'{{ p=$1; c=$2; sub(/^.*\\//, "", c); {match} {{ print p, c }} }}'
    prefix = 'ps -eo pid=,comm= | awk '
    if pattern is not None:
        prefix += f'-v pat={shlex.quote(pattern)} '
    return f'{prefix}{shlex.quote(script)}'


def _build_sh(args: argparse.Namespace) -> str:
    """Generate a POSIX shell snippet for the selected kill mode."""
    if args.pid is not None:
        n = args.pid
        if args.dry_run:
            return (
                f'if kill -0 {n} 2>/dev/null; then '
                f'ps -p {n} -o pid=,comm=; exit 0; '
                f'else echo "PID {n} not found"; exit 1; fi'
            )
        return (
            f'if kill -0 {n} 2>/dev/null; then '
            f'kill -TERM {n}; rc=$?; i=0; '
            f'while kill -0 {n} 2>/dev/null && [ "$i" -lt 20 ]; do sleep 0.1; i=$((i+1)); done; '
            f'if kill -0 {n} 2>/dev/null; then echo "PID {n} still running"; exit 1; fi; '
            'exit $rc; '
            f'else echo "PID {n} not found"; exit 1; fi'
        )

    label = 'python procs' if args.all else 'matching procs'
    rows = _posix_rows(None if args.all else args.match)
    if args.dry_run:
        return rows
    return (
        f'rows="$({rows})"; '
        'pids=$(printf "%s\\n" "$rows" | awk \'{print $1}\'); '
        'if [ -z "$pids" ]; then echo "remaining '
        f'{label}: 0"; exit 0; fi; '
        'kill -TERM $pids; rc=$?; '
        f"remaining=$({rows} | awk 'NF {{n++}} END {{print n+0}}'); "
        'i=0; '
        'while [ "$remaining" -ne 0 ] && [ "$i" -lt 20 ]; do '
        f"sleep 0.1; remaining=$({rows} | awk 'NF {{n++}} END {{print n+0}}'); i=$((i+1)); "
        'done; '
        f'echo "remaining {label}: $remaining"; '
        'if [ "$remaining" -ne 0 ]; then exit 1; fi; '
        'exit $rc'
    )


def _positive_pid(value: str) -> int:
    try:
        pid = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('PID must be a positive integer') from exc
    if pid <= 0:
        raise argparse.ArgumentTypeError('PID must be a positive integer')
    return pid


def _build_parser() -> argparse.ArgumentParser:
    """argparse with cfg positional + mutex group(--all / --pid / --match)."""
    p = argparse.ArgumentParser(description='Kill python processes via cfg-driven local/ssh dispatch.')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument('--all', action='store_true', help='kill all python.exe')
    g.add_argument('--pid', type=_positive_pid, help='kill a single PID')
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
    own_pid = os.getpid()
    return [int(x) for x in r.stdout.split() if x.strip().isdigit() and int(x) != own_pid]


def _pid_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


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
    deadline = time.monotonic() + KILL_WAIT_SECONDS
    remaining = [pid for pid in pids if _pid_exists(pid)]
    while remaining and time.monotonic() < deadline:
        time.sleep(KILL_POLL_SECONDS)
        remaining = [pid for pid in remaining if _pid_exists(pid)]
    if remaining:
        sys.stderr.write(f'[local.kill] remaining processes: {remaining}\n')
        return 1
    return rc


def _run_remote(remote, args: argparse.Namespace) -> int:
    """Remote ssh dispatch — send the OS-specific body directly(not python -m self,which
    would recurse)。"""
    if remote.os == 'windows':
        script = _build_ps(args)
    else:
        script = _build_sh(args)
    tag = 'dry-run' if args.dry_run else 'kill'
    print(f'[remote.kill] ({tag}) {remote.ssh} >> {script}')
    if remote.os == 'windows':
        r = ssh_run(remote, script, timeout=args.timeout)
    else:
        r = ssh_run_bash(remote, script, timeout=args.timeout)
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
