"""Run a Python module on the remote host via ssh — cfg-driven dispatch。

CLI:

    .venv/bin/python -m tools.runs._ssh <cfg.toml> [--stream] [--timeout S] -- <remote argv...>

cfg ``[meta].host == 'local'``(或 socket.gethostname() == [remote].hostname)
→ exec argv locally; ``remote`` → ssh wrap。``--`` 分割 wrapper 参数与远程
命令。PS prelude 设 OMP/MKL/PYTHONIOENCODING/PYTHONUNBUFFERED。

Modes:
    default     capture_output=True;命令结束统一 print stdout/stderr。短命令用。
    --stream    Popen + 逐行实时打到 local stdout/stderr。长跑训练用,避免零反馈。

`ssh_forward()` 是 helper for the other public tools(kill / tail / pull /
_remote_sync / status / build_engine)— 自动 probe 远端 python + ssh-wrap
``<python> -X utf8 -u -m <tool> <cfg> <args...>``。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import IO

from tools.runs._host import (
    RemoteCfg,
    discover_remote_python,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    ssh_encoded_argv,
    ssh_run,
)


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


def _run_stream(argv: list[str], timeout: int) -> int:
    """Popen ssh + line-buffer pump stdout/stderr to local. timeout is
    wall-clock; on expiry SIGTERM the child."""
    proc = subprocess.Popen(
        argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, errors='replace', bufsize=1
    )
    t_out = threading.Thread(target=_pump, args=(proc.stdout, sys.stdout), daemon=True)
    t_err = threading.Thread(target=_pump, args=(proc.stderr, sys.stderr), daemon=True)
    t_out.start()
    t_err.start()
    deadline = time.monotonic() + timeout
    try:
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
    except KeyboardInterrupt:
        sys.stderr.write('[remote.run] SIGINT — terminating remote ssh proc\n')
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        rc = proc.returncode if proc.returncode is not None else 130
    t_out.join(timeout=2)
    t_err.join(timeout=2)
    return rc


def ssh_forward(
    remote: RemoteCfg,
    tool_module: str,
    cfg_path: Path,
    extra_args: list[str],
    stream: bool = False,
    timeout: int = 86400,
) -> int:
    """Compose+exec ssh argv that runs ``<python> -X utf8 -u -m <tool_module>
    <cfg> <extra>`` on remote。Probe python once via ``discover_remote_python``;
    stream stdout/stderr through; return exit code。

    ``cfg_path`` is the *remote* cfg path — for now we assume the local
    repo tree is rsync'd to ``remote.root`` (per ``_remote_sync``), so
    relative cfg paths resolve identically on both sides。

    Quoting: ``cfg_path`` + each ``extra_args`` token go through
    ``ps_quote`` so user-controlled values that contain spaces, ``;``,
    ``|``, ``&`` etc. cannot break out of the PS-encoded payload
    (``--EncodedCommand`` already neutralizes cmd.exe metachars, but
    inside the PS payload itself we still need single-quote wrapping to
    prevent re-tokenization). ``py`` + ``tool_module`` are probe/literal
    surfaces and not quoted — they only contain safe chars by
    construction (interpreter path from ``discover_remote_python`` is a
    venv path with no quoting hazards; ``tool_module`` is a literal
    dotted name controlled by the calling tool).
    """
    py = discover_remote_python(remote)
    cfg_str = str(cfg_path).replace('\\', '/')
    cd_root = f'cd {ps_quote(remote.root_native)}'
    quoted_cfg = ps_quote(cfg_str)
    quoted_extra = ' '.join(ps_quote(a) for a in extra_args)
    inner = f'{py} -X utf8 -u -m {tool_module} {quoted_cfg}'
    if quoted_extra:
        inner = f'{inner} {quoted_extra}'
    ps = f'{cd_root}; {inner}'
    argv = ssh_encoded_argv(remote, ps)
    print(f'[remote.forward] {remote.ssh} >> {tool_module} {cfg_str} {" ".join(extra_args)}')
    if stream:
        return _run_stream(argv, timeout=timeout)
    r = subprocess.run(argv, capture_output=True, text=True, errors='replace', timeout=timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog='tools.runs._ssh')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument(
        '--cwd',
        default=None,
        help='override remote cwd (default: cfg [remote].root)',
    )
    p.add_argument('--timeout', type=int, default=86400, help='wall-clock seconds, default 1 day')
    p.add_argument('--stream', action='store_true', help='real-time stdout/stderr stream (long-running)')
    p.add_argument('cmd', nargs=argparse.REMAINDER, help='-- followed by remote command tokens')
    return p


def main() -> int:
    args = _build_parser().parse_args()
    if not args.cmd:
        sys.stderr.write('error: no command given (use -- to separate)\n')
        return 2
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        # Local exec — strip leading `--`, run tokens directly。
        cmd_tokens = [c for c in args.cmd if c != '--']
        if not cmd_tokens:
            sys.stderr.write('error: empty command after `--`\n')
            return 2
        print(f'[run.local] >> {" ".join(cmd_tokens)}' + ('  (stream)' if args.stream else ''))
        try:
            if args.stream:
                proc = subprocess.Popen(cmd_tokens)
                return proc.wait(timeout=args.timeout)
            r = subprocess.run(cmd_tokens, timeout=args.timeout)
            return r.returncode
        except FileNotFoundError as e:
            sys.stderr.write(f'error: {e}\n')
            return 127
    # Remote exec via PS-encoded ssh。
    assert remote is not None  # narrowed by is_local_host
    cwd = args.cwd if args.cwd is not None else remote.root_native
    ps, raw = _build_ps(args.cmd, cwd)
    argv = ssh_encoded_argv(remote, ps)
    print(f'[remote.run] {remote.ssh} >> {raw}' + ('  (stream)' if args.stream else ''))
    if args.stream:
        return _run_stream(argv, timeout=args.timeout)
    r = ssh_run(remote, ps, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
