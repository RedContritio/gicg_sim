"""Pull from a Windows remote via tar and SCP.

CLI:

    .venv/bin/python -m tools.runs.pull <cfg.toml> <run-label> [--all-ckpts]
    .venv/bin/python -m tools.runs.pull <cfg.toml> --dir <remote-path>
    .venv/bin/python -m tools.runs.pull <cfg.toml> --files <glob>

3 mutually exclusive modes:

- ``<run-label>`` legacy:pull ``artifacts/<run>/`` 默认排除 per-step ckpts
  (``ckpt_*.pt`` / ``gauntlet_*.pt``);``--all-ckpts`` 全拉。
- ``--dir <remote>``:tar 整 dir。
- ``--files <glob>``:ssh PS ``Get-ChildItem`` 解析 glob → tar list。

The remote implementation uses PowerShell. If ``[meta].host == 'local'``
(or hostname loopback), pull is a no-op because source and destination match.
"""

from __future__ import annotations

import argparse
import re
import shlex
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

from tools.runs._host import (
    RemoteCfg,
    is_local_host,
    load_remote_from_cfg,
    ps_quote,
    scp_from,
    ssh_run,
    ssh_run_bash,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument('cfg', type=Path, help='Training cfg toml; [meta].host decides local vs remote')
    p.add_argument('run_label', type=str, nargs='?', default=None)
    p.add_argument('--dir', dest='dir_', type=str, default=None, help='pull entire remote dir')
    p.add_argument('--files', type=str, default=None, help='glob pattern (resolved via PS Get-ChildItem)')
    p.add_argument('--local-root', default='artifacts')
    p.add_argument('--all-ckpts', action='store_true', help='legacy mode: include per-step ckpts')
    return p


def _to_rel(remote: RemoteCfg, remote_path: str) -> str:
    """Path → ``remote.root``-relative(strip leading)。"""
    norm = remote_path.replace('\\', '/').rstrip('/')
    root = remote.root.rstrip('/')
    if remote.os == 'windows':
        comparable_norm = norm.lower()
        comparable_root = root.lower()
    else:
        comparable_norm = norm
        comparable_root = root
    if comparable_norm == comparable_root:
        return ''
    prefix = comparable_root if comparable_root.endswith('/') else f'{comparable_root}/'
    if comparable_norm.startswith(prefix):
        return norm[len(root) :].lstrip('/')
    is_absolute = norm.startswith('/') or re.match(r'^[A-Za-z]:/', norm) is not None
    if is_absolute:
        raise ValueError(f'absolute path outside remote root {remote.root}: {norm}')
    return norm.lstrip('/')


def _local_mirror(remote_rel: str, local_root: str) -> Path:
    """``artifacts/<run>/<sub>/`` → ``<local_root>/<run>/<sub>/``;否则 basename。"""
    pure = remote_rel.replace('\\', '/').rstrip('/')
    parts = Path(pure).parts
    if parts and parts[0] == 'artifacts':
        return Path(local_root).joinpath(*parts[1:])
    return Path(local_root) / Path(pure).name


def _pull_via_tar(
    remote: RemoteCfg,
    rel_paths: list[str],
    extract_root: Path,
    excludes: list[str] | None = None,
    tar_cwd: str | None = None,
    timeout: int = 600,
) -> int:
    """ssh tar -czf X.tar.gz → scp_from → local untar。

    rel_paths relative to ``tar_cwd``(forward-slash form). ``tar_cwd``
    defaults to ``remote.root_native``;legacy uses ``<root>/artifacts``
    so tar archive's internal paths drop the ``artifacts/`` prefix。
    tar file 本身始终写到 ``remote.root_native``,scp_from + cleanup 路径不变。
    """
    if not rel_paths:
        print('[pull] refusing empty tar path list', file=sys.stderr)
        return 1
    rel_paths = [p or '.' for p in rel_paths]
    cwd = tar_cwd if tar_cwd is not None else remote.root_native
    sep = '\\' if remote.os == 'windows' else '/'
    remote_tar = f'pull_{uuid.uuid4().hex[:8]}.tar.gz'
    tar_abs = f'{remote.root_native}{sep}{remote_tar}'
    tar_excludes = [*(excludes or []), remote_tar, f'./{remote_tar}']
    print(f'[pull] remote tar: {len(rel_paths)} path(s) → {remote_tar}')
    if remote.os == 'windows':
        paths_arg = ' '.join(ps_quote(p) for p in rel_paths)
        excl_args = ''.join(f' --exclude={ps_quote(e)}' for e in tar_excludes)
        ps = f'cd {ps_quote(cwd)}; tar -czf {ps_quote(tar_abs)}{excl_args} {paths_arg}'
        r = ssh_run(remote, ps, timeout=timeout)
    else:
        paths_arg = ' '.join(shlex.quote(p) for p in rel_paths)
        excl_args = ''.join(f' --exclude={shlex.quote(e)}' for e in tar_excludes)
        sh = f'cd {shlex.quote(cwd)} && tar -czf {shlex.quote(tar_abs)}{excl_args} {paths_arg}'
        r = ssh_run_bash(remote, sh, timeout=timeout)
    if r.returncode != 0:
        print(f'[pull] remote tar failed: {r.stderr.strip()}', file=sys.stderr)
        return r.returncode
    with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as fh:
        tar_path = Path(fh.name)
    try:
        r = scp_from(remote, remote_tar, tar_path, timeout=timeout)
        if r.returncode != 0:
            print(f'[pull] scp failed: {r.stderr.strip()}', file=sys.stderr)
            return r.returncode
        extract_root.mkdir(parents=True, exist_ok=True)
        with tarfile.open(tar_path, 'r:gz') as tar:
            tar.extractall(extract_root)
        size_kb = tar_path.stat().st_size // 1024
        print(f'[pull] extracted {size_kb} KB → {extract_root}')
        return 0
    finally:
        tar_path.unlink(missing_ok=True)
        if remote.os == 'windows':
            cleanup = (
                f'Remove-Item {ps_quote(f"{remote.root_native}{sep}{remote_tar}")} -Force -ErrorAction SilentlyContinue'
            )
            ssh_run(remote, cleanup, timeout=30)
        else:
            ssh_run_bash(remote, f'rm -f -- {shlex.quote(tar_abs)}', timeout=30)


def _run_legacy(remote: RemoteCfg, args) -> int:
    excludes = [] if args.all_ckpts else ['ckpts/ckpt_*.pt', 'ckpts/gauntlet_*.pt']
    sep = '\\' if remote.os == 'windows' else '/'
    return _pull_via_tar(
        remote,
        [args.run_label],
        extract_root=Path(args.local_root),
        excludes=excludes,
        tar_cwd=f'{remote.root_native}{sep}artifacts',
    )


def _strip_artifacts_prefix(rel_paths: list[str]) -> tuple[list[str], bool]:
    """Strip leading ``artifacts/`` component from each path.

    Returns ``(stripped, all_had_prefix)``. If **any** path lacks the prefix,
    returns the original list unchanged with ``False``.
    """
    stripped = []
    for p in rel_paths:
        parts = Path(p).parts
        if parts and parts[0] == 'artifacts':
            stripped.append(str(Path(*parts[1:])))
        else:
            return rel_paths, False
    return stripped, True


def _run_dir(remote: RemoteCfg, args) -> int:
    rel = _to_rel(remote, args.dir_.rstrip('/'))
    rel = rel or '.'
    if rel == '.':
        return _pull_via_tar(remote, ['.'], extract_root=Path('.'))
    stripped, ok = _strip_artifacts_prefix([rel])
    if ok:
        stripped = stripped or ['.']
        sep = '\\' if remote.os == 'windows' else '/'
        return _pull_via_tar(
            remote,
            stripped,
            extract_root=Path(args.local_root),
            tar_cwd=f'{remote.root_native}{sep}artifacts',
        )
    return _pull_via_tar(remote, [rel], extract_root=Path('.'))


def _resolve_glob(remote: RemoteCfg, glob: str) -> list[str]:
    """Resolve a remote glob to ``remote.root``-relative paths."""
    abs_glob = glob if ':' in glob else f'{remote.root}/{glob.lstrip("/")}'
    if remote.os == 'windows':
        ps = f'Get-ChildItem -Path {ps_quote(abs_glob)} -File | Select-Object -ExpandProperty FullName'
        r = ssh_run(remote, ps)
    else:
        root = remote.root.rstrip('/') or '/'
        if glob.startswith('/'):
            pattern = glob
            search_root = root
        else:
            pattern = f'{root}/{glob.lstrip("/")}'
            search_root = root
        r = ssh_run_bash(
            remote,
            f'find {shlex.quote(search_root)} -path {shlex.quote(pattern)} -type f -print',
        )
    if r.returncode != 0:
        raise RuntimeError(f'remote glob ls failed: {r.stderr.strip()}')
    abs_paths = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return [_to_rel(remote, p) for p in abs_paths]


def _run_files(remote: RemoteCfg, args) -> int:
    try:
        rel_paths = _resolve_glob(remote, args.files)
    except (RuntimeError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    if not rel_paths:
        print(f'error: no remote files matched glob: {args.files}', file=sys.stderr)
        return 1
    stripped, ok = _strip_artifacts_prefix(rel_paths)
    if ok:
        sep = '\\' if remote.os == 'windows' else '/'
        return _pull_via_tar(
            remote,
            stripped,
            extract_root=Path(args.local_root),
            tar_cwd=f'{remote.root_native}{sep}artifacts',
        )
    return _pull_via_tar(remote, rel_paths, extract_root=Path('.'))


def _run_local(args) -> int:
    """Local mode no-op — source == destination。"""
    print('[pull] cfg [meta].host=local (or loopback) — nothing to pull', file=sys.stderr)
    return 0


def main():
    args = _build_parser().parse_args()
    provided = sum(x is not None for x in [args.run_label, args.dir_, args.files])
    if provided != 1:
        print('error: exactly one of: <run-label> | --dir | --files required', file=sys.stderr)
        return 2
    remote = load_remote_from_cfg(args.cfg)
    if is_local_host(remote):
        return _run_local(args)
    assert remote is not None
    if args.run_label:
        return _run_legacy(remote, args)
    if args.dir_:
        return _run_dir(remote, args)
    return _run_files(remote, args)


if __name__ == '__main__':
    sys.exit(main())
