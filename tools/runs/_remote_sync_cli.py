"""Command-line entry point for remote source synchronization."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.runs._host import is_local_host, load_remote_from_cfg, scp_to


def main() -> int:
    from tools.runs import _remote_sync as sync

    parser = argparse.ArgumentParser()
    parser.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--single', type=str)
    group.add_argument('--tar-all', action='store_true')
    group.add_argument('--git-changed', action='store_true', help='legacy: uncommitted only')
    group.add_argument('--auto', action='store_true', help='default: uncommitted ∪ diff(remote_sha..HEAD)')
    parser.add_argument('--from-sha', type=str, default=None, help='override base sha for committed-diff calc')
    parser.add_argument('--dry-run', action='store_true', help='print plan; no push')
    args = parser.parse_args()

    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        print('[sync] cfg [meta].host=local (or loopback) — nothing to push', file=sys.stderr)
        return 0
    assert remote is not None

    if args.single:
        if args.dry_run:
            print(f'[sync:dry-run] mode=single  {args.single}')
            return 0
        result = scp_to(remote, Path(args.single), args.single)
        if result.returncode != 0:
            print(result.stderr, file=sys.stderr)
        return result.returncode

    if args.tar_all:
        paths = [Path(directory) for directory in sync.REPO_DIRS if Path(directory).exists()]
        if args.dry_run:
            print('[sync:dry-run] mode=tar-all')
            for path in paths:
                print(f'  {path}')
            return 0
        rc = sync._tar_and_send(remote, paths, 'tar-all')
        if rc != 0:
            return rc
        manifest: dict[str, str] = {}
        for directory in sync.REPO_DIRS:
            root = Path(directory)
            if not root.exists():
                continue
            for path in root.rglob('*'):
                if path.is_file() and (digest := sync._hash_file(path)) is not None:
                    manifest[str(path)] = digest
        rc = sync._write_remote_manifest(remote, manifest)
        if rc != 0:
            print('[sync] WARN: tar-all manifest write failed (next auto re-pushes)', file=sys.stderr)
            return 0
        if sync._read_remote_manifest(remote) != manifest:
            print('[sync] ERROR: tar-all manifest verification failed', file=sys.stderr)
            return 3
        print(f'[sync] manifest verified: {len(manifest)} files tracked')
        return 0

    if args.git_changed:
        paths = sync._uncommitted_files()
        if args.dry_run:
            print(f'[sync:dry-run] mode=git-changed (uncommitted)  {len(paths)} files:')
            for path in paths:
                print(f'  {path}')
            return 0
        if not paths:
            print('[sync] nothing changed')
            return 0
        return sync._tar_and_send(remote, paths, 'git-changed')

    return sync._auto_sync(remote, dry_run=args.dry_run, base_sha_override=args.from_sha)
