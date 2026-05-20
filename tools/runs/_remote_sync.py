"""Sync Mac → Windows source.

Modes:
  (default / --auto)   since-last-sync: uncommitted ∪ git diff <last_sha> HEAD
  --git-changed        only uncommitted (legacy, kept for compat)
  --single PATH        scp a single file
  --tar-all            tar entire REPO_DIRS
  --from-sha SHA       override the base sha for the committed-diff calc
  --dry-run            print what would be synced; no push

Default mode tracks `<root_posix>/.last_synced_sha` on the remote: each
successful clean-tree sync writes local HEAD there. Dirty syncs do NOT
update the sha — next sync still re-pushes the same committed diff plus
whatever's still uncommitted. First sync (no remote sha) → all tracked
files (equivalent to --tar-all but only files git knows about).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from tools.runs._host import REMOTE_ROOT_WIN, ps_quote, scp_to, ssh_run

REPO_DIRS = ['gicg_engine', 'training', 'gicg_env', 'tools', 'data', 'configs']
LAST_SHA_FILE = '.last_synced_sha'


def _git(*args: str) -> str:
    return subprocess.run(['git', *args], capture_output=True, text=True, check=True).stdout


def _uncommitted_files() -> list[Path]:
    """Files appearing in `git status -s` that exist + are regular files."""
    out: list[Path] = []
    for line in _git('status', '-s').splitlines():
        s = line[3:].strip()
        if not s or s.startswith('.'):
            continue
        p = Path(s)
        if p.exists() and p.is_file():
            out.append(p)
    return out


def _committed_diff(base_sha: str | None) -> list[Path]:
    """Files changed between ``base_sha`` and HEAD. If base is None →
    full tracked file set (first sync)."""
    if base_sha is None:
        names = _git('ls-files').splitlines()
    else:
        names = _git('diff', f'{base_sha}..HEAD', '--name-only').splitlines()
    out: list[Path] = []
    for s in names:
        s = s.strip()
        if not s:
            continue
        p = Path(s)
        if p.exists() and p.is_file():
            out.append(p)
    return out


def _read_remote_sha() -> str | None:
    """Read `<root_posix>/.last_synced_sha` over ssh. Returns None if
    file missing or unreadable."""
    ps = (
        f'$p = Join-Path {ps_quote(REMOTE_ROOT_WIN)} {ps_quote(LAST_SHA_FILE)}; '
        f'if (Test-Path $p) {{ Get-Content -Raw $p }} else {{ "" }}'
    )
    r = ssh_run(ps)
    if r.returncode != 0:
        return None
    sha = (r.stdout or '').strip()
    return sha if sha else None


def _write_remote_sha(sha: str) -> int:
    """Write local HEAD into `<root_posix>/.last_synced_sha`."""
    ps = (
        f'$p = Join-Path {ps_quote(REMOTE_ROOT_WIN)} {ps_quote(LAST_SHA_FILE)}; '
        f'Set-Content -NoNewline -Path $p -Value {ps_quote(sha)}'
    )
    return ssh_run(ps).returncode


def _tar_and_send(paths: list[Path], label: str) -> int:
    with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as fh:
        tar_path = Path(fh.name)
    with tarfile.open(tar_path, 'w:gz') as tar:
        for p in paths:
            tar.add(p, arcname=str(p))
    print(f'[sync] {label}: {len(paths)} files, {tar_path.stat().st_size // 1024} KB')
    r = scp_to(tar_path, 'sync.tar.gz')
    if r.returncode != 0:
        print(f'[sync] scp failed: {r.stderr}', file=sys.stderr)
        return r.returncode
    r = ssh_run(f'cd "{REMOTE_ROOT_WIN}"; tar -xzf sync.tar.gz; rm sync.tar.gz')
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


def _auto_sync(dry_run: bool, base_sha_override: str | None) -> int:
    """Default mode — uncommitted ∪ committed_diff(remote_sha → HEAD)."""
    head = _git('rev-parse', 'HEAD').strip()
    base = base_sha_override if base_sha_override is not None else _read_remote_sha()
    uncommitted = _uncommitted_files()
    committed = _committed_diff(base)
    # Dedup while preserving order.
    seen: set[Path] = set()
    paths: list[Path] = []
    for p in (*committed, *uncommitted):
        if p not in seen:
            seen.add(p)
            paths.append(p)
    clean = not uncommitted
    label = 'auto (first-sync, ls-files)' if base is None else f'auto (diff {base[:12]}..HEAD)'
    if dry_run:
        _print_plan(label, paths, base, head, clean)
        return 0
    if not paths:
        print(f'[sync] nothing to push (remote already at {head[:12]})')
        return 0
    rc = _tar_and_send(paths, label)
    if rc != 0:
        return rc
    # Only advance sha pointer on clean trees — uncommitted means the
    # next push must re-include the same committed diff + still-dirty
    # files, so don't move the base.
    if clean:
        wrc = _write_remote_sha(head)
        if wrc != 0:
            print('[sync] WARN: failed to update remote .last_synced_sha', file=sys.stderr)
        else:
            print(f'[sync] remote .last_synced_sha → {head[:12]}')
    else:
        print('[sync] uncommitted files present — leaving remote .last_synced_sha unchanged')
    return 0


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument('--single', type=str)
    g.add_argument('--tar-all', action='store_true')
    g.add_argument('--git-changed', action='store_true', help='legacy: uncommitted only')
    g.add_argument('--auto', action='store_true', help='default: uncommitted ∪ diff(remote_sha..HEAD)')
    p.add_argument('--from-sha', type=str, default=None, help='override base sha for committed-diff calc')
    p.add_argument('--dry-run', action='store_true', help='print plan; no push')
    args = p.parse_args()

    if args.single:
        if args.dry_run:
            print(f'[sync:dry-run] mode=single  {args.single}')
            return 0
        r = scp_to(Path(args.single), args.single)
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
        return _tar_and_send(paths, 'tar-all')

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
        return _tar_and_send(paths, 'git-changed')

    # Default: auto / since-last-sync.
    return _auto_sync(dry_run=args.dry_run, base_sha_override=args.from_sha)


if __name__ == '__main__':
    sys.exit(main())
