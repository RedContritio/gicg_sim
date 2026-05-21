"""tools.runs.profile — cfg-driven dispatch wrapper for DMC perf tools.

Thin wrapper that auto-syncs the repo to the remote box (via
``tools.runs._remote_sync``) and ssh-forwards
``tools.dmc.profile_{actor,train}`` execution。 cfg's ``[meta].host`` +
``[remote]`` section drive local vs remote dispatch (loopback hostname
match → local fall-through;remote → auto-sync + ssh forward, streamed)。

Local fall-through delegates to the underlying ``tools.dmc.profile_*``
module via ``subprocess.run`` (no in-process import to avoid the cProfile
re-entrancy + argv-mutation hazard)。

CLI:

    tools.runs.profile actor <cfg> [--duration-seconds N] [--prof-output P] [--top-hotspots N]
    tools.runs.profile train <cfg> [--duration-seconds N] [--warmup-seconds N]
                                   [--tail-seconds N] [--prof-output P] [--top-hotspots N]

cfg must include ``[remote]`` 4-field section per I30 cfg-driven convention
(ssh / root / os / hostname)。 Local mode skips dispatch entirely。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools.runs._host import (
    discover_remote_python,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    ssh_encoded_argv,
)
from tools.runs._ssh import _run_stream


def _dispatch_remote(cfg_path: Path, tool: str, extra_args: list[str]) -> int:
    remote = load_remote_from_cfg(cfg_path)
    assert remote is not None

    sync_argv = [sys.executable, '-m', 'tools.runs._remote_sync', str(cfg_path)]
    print(f'[profile.remote] auto-sync: {" ".join(sync_argv)}', file=sys.stderr)
    sync = subprocess.run(sync_argv)
    if sync.returncode != 0:
        print(
            f'[profile.remote] sync failed (rc={sync.returncode}), aborting',
            file=sys.stderr,
        )
        return sync.returncode

    py = discover_remote_python(remote)
    target = f'tools.dmc.profile_{tool}'
    cfg_str = str(cfg_path).replace('\\', '/')
    cd_root = f'cd {ps_quote(remote.root_native)}'
    full_args = ['--cfg', cfg_str] + extra_args
    quoted_args = ' '.join(ps_quote(a) for a in full_args)
    inner = f'{py} -X utf8 -u -m {target} {quoted_args}'
    ps = f'{cd_root}; {inner}'
    argv = ssh_encoded_argv(remote, ps)
    print(
        f'[profile.remote] {remote.ssh} >> {target} {" ".join(full_args)}',
        file=sys.stderr,
    )
    return _run_stream(argv, timeout=86400)


def _local_exec(cfg_path: Path, tool: str, extra_args: list[str]) -> int:
    target = f'tools.dmc.profile_{tool}'
    argv = [sys.executable, '-m', target, '--cfg', str(cfg_path)] + extra_args
    print(f'[profile.local] >> {" ".join(argv[1:])}', file=sys.stderr)
    return subprocess.run(argv).returncode


def _build_extra_args(tool: str, args: argparse.Namespace) -> list[str]:
    extra: list[str] = []
    if args.duration_seconds is not None:
        extra += ['--duration-seconds', str(args.duration_seconds)]
    if args.prof_output is not None:
        extra += ['--prof-output', args.prof_output]
    if args.top_hotspots is not None:
        extra += ['--top-hotspots', str(args.top_hotspots)]
    if tool == 'train':
        if args.warmup_seconds is not None:
            extra += ['--warmup-seconds', str(args.warmup_seconds)]
        if args.tail_seconds is not None:
            extra += ['--tail-seconds', str(args.tail_seconds)]
    return extra


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog='tools.runs.profile',
        description='cfg-driven DMC perf benchmark wrapper (auto-sync + ssh forward to tools.dmc.profile_*).',
    )
    parser.add_argument('tool', choices=['actor', 'train'], help='which DMC profile harness to run')
    parser.add_argument('cfg', type=str, help='path to TOML cfg (must include [remote] for remote dispatch)')
    parser.add_argument('--duration-seconds', type=int, default=None, help='wall budget (tool default kicks in if omitted)')
    parser.add_argument('--warmup-seconds', type=int, default=None, help='profile_train Phase 1 wall (train only)')
    parser.add_argument('--tail-seconds', type=int, default=None, help='profile_train Phase 3 wall (train only)')
    parser.add_argument('--prof-output', type=str, default=None, help='cProfile output path (tool default if omitted)')
    parser.add_argument('--top-hotspots', type=int, default=None, help='how many cumtime rows to print')
    args = parser.parse_args(argv)

    cfg_path = Path(args.cfg)
    extra = _build_extra_args(args.tool, args)

    if cfg_path.is_file():
        remote = load_remote_from_cfg(cfg_path)
        if not is_local_host(remote):
            return _dispatch_remote(cfg_path, args.tool, extra)
    return _local_exec(cfg_path, args.tool, extra)


if __name__ == '__main__':
    sys.exit(main())
