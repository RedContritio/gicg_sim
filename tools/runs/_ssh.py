"""SSH transport and cfg-driven remote command dispatch.

CLI:

    .venv/bin/python -m tools.runs._ssh <cfg.toml> [--stream] [--timeout S] -- <remote argv...>

Public CLI: :mod:`tools.runs.exec`.

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
import os
import shlex
import sys
from pathlib import Path

from tools.runs._host import (
    RemoteCfg,
    discover_remote_python,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    run_argv,
    run_argv_capture,
    ssh_bash_argv,
    ssh_encoded_argv,
    ssh_run,
    ssh_run_bash,
    stream_argv,
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


def _build_sh(cmd_tokens: list[str], cwd: str) -> tuple[str, str]:
    """Return (bash_script, raw_cmd_for_logging)."""
    raw = ' '.join(c for c in cmd_tokens if c != '--')
    command = ' '.join(shlex.quote(c) for c in cmd_tokens if c != '--')
    sh = (
        f'cd {shlex.quote(cwd)} && '
        'OMP_NUM_THREADS=1 MKL_NUM_THREADS=1 PYTHONIOENCODING=utf-8 PYTHONUNBUFFERED=1 '
        f'{command}'
    )
    return sh, raw


def _run_stream(argv: list[str], timeout: int) -> int:
    return stream_argv(argv, timeout=timeout, label='[remote.run]')


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
    # GOGC forward (09-19): user-level Windows env vars do NOT reach
    # processes spawned by an already-running sshd, so when the local
    # launcher sets GOGC (engine Go runtime tuning, measured 1.16x step
    # speedup) we inline it into the remote payload instead.
    gogc_prefix = ''
    if os.environ.get('GOGC'):
        gogc_prefix = (
            f'$env:GOGC={ps_quote(os.environ["GOGC"])}; '
            if remote.os == 'windows'
            else f'GOGC={shlex.quote(os.environ["GOGC"])} '
        )
    if remote.os == 'windows':
        cd_root = f'cd {ps_quote(remote.root_native)}'
        quoted_cfg = ps_quote(cfg_str)
        quoted_extra = ' '.join(ps_quote(a) for a in extra_args)
        inner = f'{py} -X utf8 -u -m {tool_module} {quoted_cfg}'
        if quoted_extra:
            inner = f'{inner} {quoted_extra}'
        script = f'{gogc_prefix}{cd_root}; {inner}'
        argv = ssh_encoded_argv(remote, script)
    else:
        cd_root = f'cd {shlex.quote(remote.root)}'
        quoted_cfg = shlex.quote(cfg_str)
        quoted_extra = ' '.join(shlex.quote(a) for a in extra_args)
        inner = f'{shlex.quote(py)} -X utf8 -u -m {tool_module} {quoted_cfg}'
        if quoted_extra:
            inner = f'{inner} {quoted_extra}'
        script = f'{gogc_prefix}{cd_root} && {inner}'
        argv = ssh_bash_argv(remote, script)
    print(f'[remote.forward] {remote.ssh} >> {tool_module} {cfg_str} {" ".join(extra_args)}')
    if stream:
        return _run_stream(argv, timeout=timeout)
    r = run_argv_capture(argv, timeout=timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def _build_parser(prog: str = 'tools.runs._ssh') -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog=prog)
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


def main(argv: list[str] | None = None, *, prog: str = 'tools.runs._ssh') -> int:
    args = _build_parser(prog).parse_args(argv)
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
                return stream_argv(cmd_tokens, timeout=args.timeout, label='[run.local]')
            r = run_argv(cmd_tokens, timeout=args.timeout)
            return r.returncode
        except FileNotFoundError as e:
            sys.stderr.write(f'error: {e}\n')
            return 127
    # Remote exec via OS-specific ssh wrapper。
    assert remote is not None  # narrowed by is_local_host
    cwd = args.cwd if args.cwd is not None else remote.root_native
    if remote.os == 'windows':
        script, raw = _build_ps(args.cmd, cwd)
        argv = ssh_encoded_argv(remote, script)
        runner = ssh_run
    else:
        script, raw = _build_sh(args.cmd, cwd)
        argv = ssh_bash_argv(remote, script)
        runner = ssh_run_bash
    print(f'[remote.run] {remote.ssh} >> {raw}' + ('  (stream)' if args.stream else ''))
    if args.stream:
        return _run_stream(argv, timeout=args.timeout)
    r = runner(remote, script, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
