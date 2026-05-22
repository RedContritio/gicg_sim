"""Build all c-shared libs(libgicg + libgicg_actor)on remote box via cgo — cfg-driven dispatch。

CLI:

    .venv/bin/python -m tools.runs.build_engine <cfg.toml>

Probes ``go`` + ``gcc`` on the remote PATH(``discover_remote_binary``);
both must already be installed + on PATH。 ``gcc`` path is no longer
prepended — that's a deploy-side concern。

Outputs:
  - Windows  → ``<remote.root>\\gicg_env\\libgicg.dll`` + ``libgicg_actor.dll``
  - POSIX    → ``<remote.root>/gicg_env/libgicg.so`` + ``libgicg_actor.so``

Build 顺序:engine 先 → actor(import gicg_engine 单向依赖)。 任一失败 fail loud +
后续 lib 不 build(防混淆状态)。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.runs._host import (
    RemoteCfg,
    discover_remote_binary,
    is_local_host,
    load_remote_from_cfg,
    ssh_run,
    ssh_run_bash,
)


# Lib targets — (output_filename_no_ext, source_path)。 build 顺序遵循依赖图:engine
# 先(actor 内 import gicg_engine)。 加新 lib 在此列表追加即可,_build_ps_windows /
# _build_sh_posix 自动迭代。
_LIB_TARGETS = [
    ('libgicg', './gicg_engine/capi/'),
    ('libgicg_actor', './gicg_actor/capi/'),
]


def _build_ps_windows(remote: RemoteCfg) -> str:
    """Single-quote env var value — Win OpenSSH cmd.exe wrapper strips
    unescaped double quotes(同 ``_ssh.py`` 注释)。 链式 build 用 `;` + `if (LASTEXITCODE -ne 0) {exit ...}`
    保证任一失败立即退出。

    ``go build -a``:force rebuild of all packages,绕过 Go build cache。 没有 -a 时
    cgo ``//export`` 表变更(加 / 改 export func)Go cache 可能 stale,生成的 dll
    export 表 与新源不一致 → ctypes call 找不到 symbol(I29 P1.5 Win box 实测踩坑)。
    -a 代价 ~5-10s/lib,P1.5 stress 时省下 manual ``go clean -cache`` 心智 + 防 silent
    corrupt build。
    """
    parts = [
        '$env:CGO_ENABLED=1',
        "$env:CC='gcc'",
        f'cd "{remote.root_native}"',
    ]
    for name, src in _LIB_TARGETS:
        # Win src 路径用反斜杠 — 同 _LIB_TARGETS 来源是 POSIX 风格,这里转换。
        src_win = src.replace('/', '\\').rstrip('\\')
        parts.append(f'go build -a -buildmode=c-shared -o gicg_env\\{name}.dll {src_win}')
        parts.append('if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }')
    return '; '.join(parts)


def _build_sh_posix(remote: RemoteCfg) -> str:
    """Same -a rationale as Windows path — 防 cgo ``//export`` cache stale。"""
    parts = [f'cd {remote.root}', 'CGO_ENABLED=1']
    for name, src in _LIB_TARGETS:
        parts.append(f'go build -a -buildmode=c-shared -o gicg_env/{name}.so {src}')
    # `set -e`-like:` && ` 链接保证任一失败短路。
    return ' && '.join(parts)


def _run_remote(remote: RemoteCfg, timeout: int) -> int:
    # Probe-first — fail loud + actionable if go or gcc absent。
    discover_remote_binary(remote, 'go')
    if remote.os == 'windows':
        discover_remote_binary(remote, 'gcc')
        ps = _build_ps_windows(remote)
        print(f'[build_engine] {remote.ssh} (windows) >> {ps}')
        r = ssh_run(remote, ps, timeout=timeout)
    else:
        discover_remote_binary(remote, 'gcc')
        sh = _build_sh_posix(remote)
        print(f'[build_engine] {remote.ssh} ({remote.os}) >> {sh}')
        r = ssh_run_bash(remote, sh, timeout=timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


def _run_local(args) -> int:
    """Local — defer to user's normal build command(makes no sense to
    re-implement here)。"""
    sys.stderr.write(
        '[build_engine] cfg [meta].host=local (or loopback); build directly:\n'
        '  go build -buildmode=c-shared -o gicg_env/libgicg.dylib ./gicg_engine/capi/\n'
        '  go build -buildmode=c-shared -o gicg_env/libgicg_actor.dylib ./gicg_actor/capi/\n'
    )
    return 1


def main():
    p = argparse.ArgumentParser(description='cgo build libgicg shared lib on the cfg-selected host.')
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument('--timeout', type=int, default=300, help='ssh wall-clock seconds, default 300')
    args = p.parse_args()
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None
    return _run_remote(remote, timeout=args.timeout)


if __name__ == '__main__':
    sys.exit(main())
