"""Sync Mac → Windows source.

Modes:
  --single PATH        scp a single file
  --tar-all            tar entire REPO_DIRS
  --git-changed        tar `git status -s` files (default)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from tools.remote._common import REMOTE_ROOT_WIN, scp_to, ssh_run

REPO_DIRS = ['gicg_engine', 'training', 'gicg_env', 'tools', 'data', 'configs']


def _changed_files() -> list[Path]:
    r = subprocess.run(['git', 'status', '-s'], capture_output=True, text=True, check=True)
    out: list[Path] = []
    for line in r.stdout.splitlines():
        s = line[3:].strip()
        if not s or s.startswith('.'):
            continue
        p = Path(s)
        if p.exists() and p.is_file():
            out.append(p)
    return out


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


def main():
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group()
    g.add_argument('--single', type=str)
    g.add_argument('--tar-all', action='store_true')
    g.add_argument('--git-changed', action='store_true')
    args = p.parse_args()

    if args.single:
        r = scp_to(Path(args.single), args.single)
        if r.returncode != 0:
            print(r.stderr, file=sys.stderr)
        return r.returncode
    if args.tar_all:
        return _tar_and_send([Path(d) for d in REPO_DIRS if Path(d).exists()], 'tar-all')
    # default → git-changed
    paths = _changed_files()
    if not paths:
        print('[sync] nothing changed')
        return 0
    return _tar_and_send(paths, 'git-changed')


if __name__ == '__main__':
    sys.exit(main())
