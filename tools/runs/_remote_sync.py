"""Synchronize local source to a configured remote host."""

from __future__ import annotations

import shlex
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from tools.runs._host import (
    RemoteCfg,
    ps_quote,
    scp_to,
    ssh_run,
    ssh_run_bash,
)
from tools.runs._sync_manifest import (
    hash_file as _hash_file,
    read_remote_manifest as _read_remote_manifest,
    write_remote_manifest as _write_remote_manifest,
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
    return [Path(name) for name in names if name and Path(name).is_file()]


def _deleted_since_commit(base_sha: str | None) -> list[Path]:
    """Paths removed since ``base_sha``; renaming is detected as delete plus add."""
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
    `Remove-Item -LiteralPath @(...) -Force -ErrorAction Stop`;
    POSIX → `rm -f`。 容忍缺失(idempotent)。 空 list → no-op。"""
    if not paths:
        return 0
    if remote.os == 'windows':
        # Win 路径反斜杠;PowerShell array literal `@('a','b')`。
        ps_paths = ', '.join(ps_quote(str(p).replace('/', '\\')) for p in paths)
        ps = (
            f'$paths = @({ps_paths}); '
            f'Set-Location -LiteralPath {ps_quote(remote.root_native)} -ErrorAction Stop; '
            'try { foreach ($path in $paths) { '
            'if (Test-Path -LiteralPath $path) { '
            'Remove-Item -LiteralPath $path -Force -ErrorAction Stop; '
            'if (Test-Path -LiteralPath $path) { throw "failed to remove $path" } '
            '} }; exit 0 } catch { Write-Error $_; exit 1 }'
        )
        r = ssh_run(remote, ps)
    else:
        files = ' '.join(shlex.quote(str(p)) for p in paths)
        sh = f'cd {shlex.quote(remote.root)} && rm -f -- {files}'
        r = ssh_run_bash(remote, sh)
    if r.returncode != 0:
        print(f'[sync] remote delete failed: {r.stderr}', file=sys.stderr)
    return r.returncode


def _read_remote_sha(remote: RemoteCfg) -> str | None:
    """Read ``<remote.root>/.last_synced_sha`` over ssh. Returns None if
    file missing or unreadable."""
    if remote.os == 'windows':
        ps = (
            f'$p = Join-Path {ps_quote(remote.root_native)} {ps_quote(LAST_SHA_FILE)}; '
            f'if (Test-Path $p) {{ Get-Content -Raw $p }} else {{ "" }}'
        )
        r = ssh_run(remote, ps)
    else:
        sha_file = shlex.quote(LAST_SHA_FILE)
        sh = f'cd {shlex.quote(remote.root)} && if [ -f {sha_file} ]; then cat {sha_file}; fi'
        r = ssh_run_bash(remote, sh)
    if r.returncode != 0:
        return None
    sha = (r.stdout or '').strip()
    return sha if sha else None


def _write_remote_sha(remote: RemoteCfg, sha: str) -> int:
    """Write local HEAD into ``<remote.root>/.last_synced_sha``."""
    if remote.os == 'windows':
        ps = (
            f'$p = Join-Path {ps_quote(remote.root_native)} {ps_quote(LAST_SHA_FILE)}; '
            f'Set-Content -NoNewline -Path $p -Value {ps_quote(sha)}'
        )
        return ssh_run(remote, ps).returncode
    sh = f'cd {shlex.quote(remote.root)} && printf "%s" {shlex.quote(sha)} > {shlex.quote(LAST_SHA_FILE)}'
    return ssh_run_bash(remote, sh).returncode


def _tar_and_send(remote: RemoteCfg, paths: list[Path], label: str) -> int:
    with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as fh:
        tar_path = Path(fh.name)
    try:
        with tarfile.open(tar_path, 'w:gz') as tar:
            for p in paths:
                tar.add(p, arcname=str(p))
        print(f'[sync] {label}: {len(paths)} files, {tar_path.stat().st_size // 1024} KB')
        r = scp_to(remote, tar_path, 'sync.tar.gz')
        if r.returncode != 0:
            print(f'[sync] scp failed: {r.stderr}', file=sys.stderr)
            return r.returncode
        if remote.os == 'windows':
            ps = (
                f'cd {ps_quote(remote.root_native)}; '
                'tar -xzf sync.tar.gz; $rc=$LASTEXITCODE; '
                'Remove-Item -LiteralPath sync.tar.gz -Force -ErrorAction SilentlyContinue; '
                'if ($rc -ne 0) { exit $rc }; exit 0'
            )
            r = ssh_run(remote, ps)
        else:
            sh = f'cd {shlex.quote(remote.root)} && {{ tar -xzf sync.tar.gz; rc=$?; rm -f -- sync.tar.gz; exit $rc; }}'
            r = ssh_run_bash(remote, sh)
        if r.returncode != 0:
            print(f'[sync] remote untar failed: {r.stderr}', file=sys.stderr)
        return r.returncode
    finally:
        tar_path.unlink(missing_ok=True)


def _print_plan(label: str, paths: list[Path], base_sha: str | None, head: str, clean: bool) -> None:
    print(f'[sync:dry-run] mode={label}')
    print(f'[sync:dry-run] remote_sha={base_sha or "<none>"}  local_HEAD={head}  clean_tree={clean}')
    print(f'[sync:dry-run] {len(paths)} files:')
    for p in paths:
        print(f'  {p}')


def _auto_sync(remote: RemoteCfg, dry_run: bool, base_sha_override: str | None) -> int:
    """Default mode — uncommitted ∪ committed_diff(remote_sha → HEAD)+ remote-side
    deletion of paths git 删/改名 since last sync(tar 只 upsert,不删)。

    Content-addressed (09-19): the remote manifest records the sha256 of
    every file sync has placed there; only candidates whose content hash
    changed since the last push cross the wire. After push + deletions the
    manifest is rewritten and read back for verification (D)."""
    head = _git('rev-parse', 'HEAD').strip()
    base = base_sha_override if base_sha_override is not None else _read_remote_sha(remote)
    uncommitted = _uncommitted_files()
    committed = _committed_diff(base)
    # Dedup while preserving order.
    seen: set[Path] = set()
    paths: list[Path] = []
    for p in (*committed, *uncommitted, Path('configs/hosts/hosts.toml')):
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

    # --- A: content-addressed filter (manifest may be {} on first run) --- #
    manifest = {} if dry_run else _read_remote_manifest(remote)
    local_hashes: dict[str, str] = {}
    unreadable: list[Path] = []
    to_push: list[Path] = []
    for p in paths:
        h = _hash_file(p)
        if h is None:
            unreadable.append(p)
            continue
        local_hashes[str(p)] = h
        if manifest.get(str(p)) != h:
            to_push.append(p)
    if unreadable:
        print(f'[sync] ERROR: {len(unreadable)} candidate file(s) unreadable: {unreadable[:3]}', file=sys.stderr)
        return 2

    if deletions:
        # Skip deletes the remote manifest shows as already absent (idempotent
        # re-runs of the same uncommitted deletion were re-deleting every sync).
        known = [p for p in deletions if not manifest or str(p) in manifest]
        skipped = len(deletions) - len(known)
        if skipped:
            print(f'[sync] {skipped} deletion(s) already absent on remote (manifest) — skipped')
        deletions = known
    if dry_run:
        _print_plan(label, to_push, base, head, clean)
        print(
            f'[sync:dry-run] content-filter: {len(paths)} candidates → {len(to_push)} to push ({len(paths) - len(to_push)} unchanged)'
        )
        if deletions:
            print(f'[sync:dry-run] + {len(deletions)} files to delete on remote:')
            for p in deletions:
                print(f'  - {p}')
        return 0
    if not to_push and not deletions:
        print(f'[sync] nothing changed vs remote manifest (HEAD {head[:12]})')
        if clean:
            wrc = _write_remote_sha(remote, head)
            if wrc != 0:
                print('[sync] WARN: failed to update remote .last_synced_sha', file=sys.stderr)
            else:
                print(f'[sync] remote .last_synced_sha → {head[:12]}')
        return 0
    if to_push:
        rc = _tar_and_send(remote, to_push, label)
        if rc != 0:
            return rc
    if deletions:
        print(f'[sync] deleting {len(deletions)} stale remote file(s) (git removed/renamed since last sync)')
        rc = _ssh_delete_paths(remote, deletions)
        if rc != 0:
            return rc
    # Manifest = previous entries + pushed hashes - deleted paths. Entries
    # for files synced earlier and untouched this round carry over as-is.
    for p in deletions:
        manifest.pop(str(p), None)
    manifest.update(local_hashes)
    wrc = _write_remote_manifest(remote, manifest)
    if wrc != 0:
        print('[sync] WARN: failed to write remote manifest (next sync re-pushes)', file=sys.stderr)
    else:
        # --- D: read-back verification --- #
        back = _read_remote_manifest(remote)
        expected = {k: v for k, v in manifest.items()}
        if back != expected:
            missing = sorted(set(expected) - set(back))[:5]
            diff = sorted(k for k in expected if k in back and back[k] != expected[k])[:5]
            print(
                f'[sync] ERROR: manifest verification failed (missing={missing} mismatch={diff})',
                file=sys.stderr,
            )
            return 3
        print(f'[sync] manifest verified: {len(back)} files tracked')
    # Only advance sha pointer on clean trees — uncommitted means the next
    # push must re-include the same committed diff + still-dirty files,
    # so don't move the base. The manifest already makes those re-pushes
    # content-cheap (unchanged files skip the wire).
    if clean:
        wrc = _write_remote_sha(remote, head)
        if wrc != 0:
            print('[sync] WARN: failed to update remote .last_synced_sha', file=sys.stderr)
        else:
            print(f'[sync] remote .last_synced_sha → {head[:12]}')
    else:
        print('[sync] uncommitted files present — leaving remote .last_synced_sha unchanged')
    return 0


def main() -> int:
    from tools.runs._remote_sync_cli import main as run_cli

    return run_cli()


if __name__ == '__main__':
    sys.exit(main())
