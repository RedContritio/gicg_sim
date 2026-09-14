"""Sync local source to a PowerShell-capable remote host.

CLI:

    .venv/bin/python -m tools.runs._remote_sync <cfg.toml> [mode flags]

Modes:
  (default / --auto)   since-last-sync: uncommitted ∪ git diff <last_sha> HEAD
  --git-changed        only uncommitted (legacy, kept for compat)
  --single PATH        scp a single file
  --tar-all            tar entire REPO_DIRS
  --from-sha SHA       override the base sha for the committed-diff calc
  --dry-run            print what would be synced; no push

Default mode tracks ``<remote.root>/.last_synced_sha`` on the remote:
each successful clean-tree sync writes local HEAD there. Dirty syncs do
NOT update the sha — next sync still re-pushes the same committed diff
plus whatever's still uncommitted. First sync(no remote sha)→ all tracked
files(equivalent to --tar-all but only files git knows about)。

If ``[meta].host == 'local'``(or hostname loopback)sync is a no-op
since source = destination — emits a warning + returns 0。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

import shlex

from tools.runs._host import (
    RemoteCfg,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    scp_to,
    ssh_run,
    ssh_run_bash,
)

REPO_DIRS = ['gicg_engine', 'training', 'gicg_env', 'tools', 'data', 'configs']
LAST_SHA_FILE = '.last_synced_sha'


def _git(*args: str) -> str:
    return subprocess.run(['git', *args], capture_output=True, text=True, check=True).stdout


def _uncommitted_files() -> list[Path]:
    """Files appearing in `git status -s` that exist + are regular files."""
    names = _git('diff', 'HEAD', '--name-only', '--no-renames', '-z').split('\0')
    names += _git('ls-files', '--others', '--exclude-standard', '-z').split('\0')
    return list(
        dict.fromkeys(Path(name) for name in names if name and not name.startswith('.') and Path(name).is_file())
    )


def _committed_diff(base_sha: str | None) -> list[Path]:
    """Files changed between ``base_sha`` and HEAD. If base is None →
    full tracked file set (first sync)."""
    if base_sha is None:
        names = _git('ls-files', '-z').split('\0')
    else:
        names = _git('diff', f'{base_sha}..HEAD', '--name-only', '-z').split('\0')
    out: list[Path] = []
    for s in names:
        if not s:
            continue
        p = Path(s)
        if p.exists() and p.is_file():
            out.append(p)
    return out


def _deleted_since_commit(base_sha: str | None) -> list[Path]:
    """Files deleted/renamed-away between ``base_sha`` and HEAD。 tar-based sync 只
    upsert,git 删/改名的旧路径在远端永久残留 —— 本函数返回的路径需在 remote 显式 rm。

    用 ``--diff-filter=D --name-only`` 抓 D 状态;**不开 -M**,使 rename 走 D+A
    (旧路径在 D 集合内),开 -M 则 rename 走 R 漏掉旧名。 base=None(首次 sync)→
    无 base 可 diff,返 []。
    """
    if base_sha is None:
        return []
    raw = _git('diff', '--diff-filter=D', '--no-renames', '--name-only', '-z', f'{base_sha}..HEAD')
    return [Path(name) for name in raw.split('\0') if name]


def _uncommitted_deletions() -> list[Path]:
    """`git status -s` 中 D 状态行(staged `D ` / unstaged ` D` / both `DD`)。
    `_uncommitted_files` 过滤掉了不存在的路径 → 不包含删除;本函数补集。"""
    raw = _git('diff', 'HEAD', '--diff-filter=D', '--no-renames', '--name-only', '-z')
    return [Path(name) for name in raw.split('\0') if name]


def _ssh_delete_paths(remote: RemoteCfg, paths: list[Path]) -> int:
    """Remove the listed (repo-relative) paths on remote。 Win → PowerShell
    `Remove-Item -LiteralPath @(...) -Force -ErrorAction SilentlyContinue`;
    POSIX → `rm -f`。 容忍缺失(idempotent)。 空 list → no-op。"""
    if not paths:
        return 0
    if remote.os == 'windows':
        # Win 路径反斜杠;PowerShell array literal `@('a','b')`。
        ps_paths = ', '.join(ps_quote(str(p).replace('/', '\\')) for p in paths)
        ps = (
            f'cd {ps_quote(remote.root_native)}; '
            f'Remove-Item -LiteralPath @({ps_paths}) -Force -ErrorAction SilentlyContinue'
        )
        r = ssh_run(remote, ps)
    else:
        files = ' '.join(shlex.quote(str(p)) for p in paths)
        sh = f'cd {shlex.quote(remote.root)} && rm -f {files}'
        r = ssh_run_bash(remote, sh)
    if r.returncode != 0:
        print(f'[sync] remote delete failed: {r.stderr}', file=sys.stderr)
    return r.returncode


def _read_remote_sha(remote: RemoteCfg) -> str | None:
    """Read ``<remote.root>/.last_synced_sha`` over ssh. Returns None if
    file missing or unreadable."""
    ps = (
        f'$p = Join-Path {ps_quote(remote.root_native)} {ps_quote(LAST_SHA_FILE)}; '
        f'if (Test-Path $p) {{ Get-Content -Raw $p }} else {{ "" }}'
    )
    r = ssh_run(remote, ps)
    if r.returncode != 0:
        return None
    sha = (r.stdout or '').strip()
    return sha if sha else None


def _write_remote_sha(remote: RemoteCfg, sha: str) -> int:
    """Write local HEAD into ``<remote.root>/.last_synced_sha``."""
    ps = (
        f'$p = Join-Path {ps_quote(remote.root_native)} {ps_quote(LAST_SHA_FILE)}; '
        f'Set-Content -NoNewline -Path $p -Value {ps_quote(sha)}'
    )
    return ssh_run(remote, ps).returncode


def _tar_and_send(remote: RemoteCfg, paths: list[Path], label: str) -> int:
    with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as fh:
        tar_path = Path(fh.name)
    with tarfile.open(tar_path, 'w:gz') as tar:
        for p in paths:
            tar.add(p, arcname=str(p))
    print(f'[sync] {label}: {len(paths)} files, {tar_path.stat().st_size // 1024} KB')
    r = scp_to(remote, tar_path, 'sync.tar.gz')
    if r.returncode != 0:
        print(f'[sync] scp failed: {r.stderr}', file=sys.stderr)
        return r.returncode
    r = ssh_run(remote, f'cd "{remote.root_native}"; tar -xzf sync.tar.gz; rm sync.tar.gz')
    if r.returncode != 0:
        print(f'[sync] remote untar failed: {r.stderr}', file=sys.stderr)
    tar_path.unlink(missing_ok=True)
    return r.returncode


def _print_plan(label: str, paths: list[Path], base_sha: str | None, head: str, clean: bool) -> None:
    print(f'[sync:dry-run] mode={label}')
    print(f'[sync:dry-run] remote_sha={base_sha or "<none>"}  local_HEAD={head}  clean_tree={clean}')
    print(f'[sync:dry-run] {len(paths)} files:')
    for p in paths:
        print(f'  {p}')


def _auto_sync(remote: RemoteCfg, dry_run: bool, base_sha_override: str | None) -> int:
    """Default mode — uncommitted ∪ committed_diff(remote_sha → HEAD)+ remote-side
    deletion of paths git 删/改名 since last sync(tar 只 upsert,不删)。"""
    head = _git('rev-parse', 'HEAD').strip()
    base = base_sha_override if base_sha_override is not None else _read_remote_sha(remote)
    uncommitted = _uncommitted_files()
    committed = _committed_diff(base)
    # Dedup while preserving order.
    seen: set[Path] = set()
    paths: list[Path] = []
    for p in (*committed, *uncommitted):
        if p not in seen:
            seen.add(p)
            paths.append(p)
    # Deletions:committed deletions(base..HEAD)+ uncommitted deletions(workdir/index)。
    committed_dels = _deleted_since_commit(base)
    uncommitted_dels = _uncommitted_deletions()
    seen_d: set[Path] = set()
    deletions: list[Path] = []
    for p in (*committed_dels, *uncommitted_dels):
        if p not in seen_d:
            seen_d.add(p)
            deletions.append(p)
    # clean tree = 无 modified + 无 deleted(原 `not uncommitted` 漏 deletion 子集;
    # 纯删除场景下旧逻辑把 dirty tree 误判 clean → sha 错误前进)。
    clean = not uncommitted and not uncommitted_dels
    label = 'auto (first-sync, ls-files)' if base is None else f'auto (diff {base[:12]}..HEAD)'
    if dry_run:
        _print_plan(label, paths, base, head, clean)
        if deletions:
            print(f'[sync:dry-run] + {len(deletions)} files to delete on remote:')
            for p in deletions:
                print(f'  - {p}')
        return 0
    if not paths and not deletions:
        print(f'[sync] nothing to push (remote already at {head[:12]})')
        return 0
    if paths:
        rc = _tar_and_send(remote, paths, label)
        if rc != 0:
            return rc
    if deletions:
        print(f'[sync] deleting {len(deletions)} stale remote file(s) (git removed/renamed since last sync)')
        rc = _ssh_delete_paths(remote, deletions)
        if rc != 0:
            return rc
    # Only advance sha pointer on clean trees — uncommitted means the next
    # push must re-include the same committed diff + still-dirty files,
    # so don't move the base.
    if clean:
        wrc = _write_remote_sha(remote, head)
        if wrc != 0:
            print('[sync] WARN: failed to update remote .last_synced_sha', file=sys.stderr)
        else:
            print(f'[sync] remote .last_synced_sha → {head[:12]}')
    else:
        print('[sync] uncommitted files present — leaving remote .last_synced_sha unchanged')
    return 0


def _run_local(args) -> int:
    """Local mode no-op — source == destination。"""
    print('[sync] cfg [meta].host=local (or loopback) — nothing to push', file=sys.stderr)
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    g = p.add_mutually_exclusive_group()
    g.add_argument('--single', type=str)
    g.add_argument('--tar-all', action='store_true')
    g.add_argument('--git-changed', action='store_true', help='legacy: uncommitted only')
    g.add_argument('--auto', action='store_true', help='default: uncommitted ∪ diff(remote_sha..HEAD)')
    p.add_argument('--from-sha', type=str, default=None, help='override base sha for committed-diff calc')
    p.add_argument('--dry-run', action='store_true', help='print plan; no push')
    args = p.parse_args()

    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None

    if args.single:
        if args.dry_run:
            print(f'[sync:dry-run] mode=single  {args.single}')
            return 0
        r = scp_to(remote, Path(args.single), args.single)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
        return r.returncode

    if args.tar_all:
        paths = [Path(d) for d in REPO_DIRS if Path(d).exists()]
        if args.dry_run:
            print('[sync:dry-run] mode=tar-all')
            for pp in paths:
                print(f'  {pp}')
            return 0
        return _tar_and_send(remote, paths, 'tar-all')

    if args.git_changed:
        paths = _uncommitted_files()
        if args.dry_run:
            print(f'[sync:dry-run] mode=git-changed (uncommitted)  {len(paths)} files:')
            for pp in paths:
                print(f'  {pp}')
            return 0
        if not paths:
            print('[sync] nothing changed')
            return 0
        return _tar_and_send(remote, paths, 'git-changed')

    # Default: auto / since-last-sync.
    return _auto_sync(remote, dry_run=args.dry_run, base_sha_override=args.from_sha)


if __name__ == '__main__':
    sys.exit(main())
