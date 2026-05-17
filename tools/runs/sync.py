"""``tools.runs.sync`` — rsync wrapper for cross-machine metadata sync.

Per spec T4: SHALL hardcode include / exclude so only ``artifacts/runs/``
is transferred. SHALL NOT sync ckpt or replays. ``--update`` flag
prevents newer local files being clobbered by older remote files.

CLI:

    .venv/bin/python -m tools.runs.sync pull <user>@<host>:<remote_repo_root>/
    .venv/bin/python -m tools.runs.sync push <user>@<host>:<remote_repo_root>/

Remote path must end with ``/`` (rsync rule — without trailing slash
rsync nests the local dir under the remote, which is not what we
want). We error out if missing.

Hardcoded rsync flags (NEVER user-overridable per spec T4 + risk R6):

    -av --update
    --include 'artifacts/'
    --include 'artifacts/runs/'
    --include 'artifacts/runs/*.toml'
    --exclude '*'

Local artifacts/runs/ is created automatically before pull so rsync
doesn't fail on missing destination.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from tools.runs import schema

# Hardcoded — user override forbidden per spec T4 + risk R6 (a single
# stray --exclude removal could sync 3GB of ckpt across a slow link).
RSYNC_FLAGS = (
    '-av',
    '--update',
    '--include=artifacts/',
    '--include=artifacts/runs/',
    '--include=artifacts/runs/*.toml',
    '--exclude=*',
)


def _validate_remote(remote: str) -> None:
    """Remote must be ``<user>@<host>:<path>/`` (path ends with /)."""
    if ':' not in remote:
        raise ValueError(f'remote {remote!r} must be of form <user>@<host>:<path>/ (missing colon)')
    _, _, path = remote.partition(':')
    if not path.endswith('/'):
        raise ValueError(f'remote path {path!r} must end with "/" (rsync would otherwise nest, not merge)')


def build_command(direction: str, remote: str, root: Path | None = None) -> list[str]:
    """Build the rsync argv list. Exposed for tests to assert on flags.

    ``root`` lets tests override the local repo root (we rsync from
    ``root`` so the include patterns ``artifacts/runs/`` match).
    """
    if direction not in ('pull', 'push'):
        raise ValueError(f'direction must be pull|push, got {direction!r}')
    _validate_remote(remote)
    local_root = root if root is not None else Path('.')
    local_arg = f'{local_root}/'  # trailing slash → merge contents

    cmd: list[str] = ['rsync', *RSYNC_FLAGS]
    if direction == 'pull':
        cmd += [remote, local_arg]
    else:  # push
        cmd += [local_arg, remote]
    return cmd


def _ensure_local_runs_dir(root: Path | None) -> None:
    """Create local artifacts/runs/ if missing (rsync needs dest dir)."""
    schema.runs_dir(root).mkdir(parents=True, exist_ok=True)


def sync(
    *,
    direction: str,
    remote: str,
    root: Path | None = None,
    runner=None,
) -> int:
    """Run rsync. ``runner`` is injectable so tests can mock without
    actually shelling out to rsync (which may not exist on CI / may
    actually touch the network). Default `None` → use module-level
    ``subprocess.run`` resolved at call time (so monkeypatching
    ``tools.runs.sync.subprocess.run`` from tests works)."""
    if runner is None:
        runner = subprocess.run
    cmd = build_command(direction, remote, root=root)
    _ensure_local_runs_dir(root)
    try:
        result = runner(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as e:
        raise RuntimeError(f'rsync not found on PATH ({e}); install rsync first') from e
    if result.returncode != 0:
        raise RuntimeError(f'rsync {direction} failed (exit {result.returncode}): {result.stderr.strip()}')
    if result.stdout:
        sys.stdout.write(result.stdout)
        if not result.stdout.endswith('\n'):
            sys.stdout.write('\n')
    return result.returncode


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('direction', choices=['pull', 'push'])
    ap.add_argument('remote', help='e.g. dev@192.168.31.56:/d/gicg_dev/')
    ap.add_argument('--root', default=None, help='override local repo root (testing only)')
    args = ap.parse_args(argv)
    try:
        return sync(
            direction=args.direction,
            remote=args.remote,
            root=Path(args.root) if args.root else None,
        )
    except (ValueError, RuntimeError) as e:
        print(f'tools.runs.sync: {e}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
