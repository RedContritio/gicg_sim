"""Pull Windows → Mac via tar+scp(远端 Win 无 rsync,沿 ``sync.py`` 同款
transport)。3 mutually exclusive modes:

- ``<run-label>`` legacy:pull ``artifacts/<run>/`` 默认排除 per-step ckpts
  (``ckpt_*.pt`` / ``gauntlet_*.pt``);``--all-ckpts`` 全拉。
- ``--dir <remote>``:tar 整 dir。
- ``--files <glob>``:ssh PS ``Get-ChildItem`` 解析 glob → tar list。
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import tempfile
import uuid
from pathlib import Path

from tools.runs._host import REMOTE_ROOT_POSIX, REMOTE_ROOT_WIN, ps_quote, scp_from, ssh_run


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser()
    p.add_argument('run_label', type=str, nargs='?', default=None)
    p.add_argument('--dir', dest='dir_', type=str, default=None, help='pull entire remote dir')
    p.add_argument('--files', type=str, default=None, help='glob pattern (resolved via PS Get-ChildItem)')
    p.add_argument('--local-root', default='artifacts')
    p.add_argument('--all-ckpts', action='store_true', help='legacy mode: include per-step ckpts')
    return p


def _to_rel(remote_path: str) -> str:
    """Path → REMOTE_ROOT_POSIX-relative(strip leading)。"""
    norm = remote_path.replace('\\', '/').rstrip('/')
    if norm.lower().startswith(REMOTE_ROOT_POSIX.lower()):
        return norm[len(REMOTE_ROOT_POSIX) :].lstrip('/')
    if ':' in norm:
        raise ValueError(f'absolute path outside REMOTE_ROOT: {norm}')
    return norm.lstrip('/')


def _local_mirror(remote_rel: str, local_root: str) -> Path:
    """``artifacts/<run>/<sub>/`` → ``<local_root>/<run>/<sub>/``;否则 basename。"""
    pure = remote_rel.replace('\\', '/').rstrip('/')
    parts = Path(pure).parts
    if parts and parts[0] == 'artifacts':
        return Path(local_root).joinpath(*parts[1:])
    return Path(local_root) / Path(pure).name


def _pull_via_tar(
    rel_paths: list[str],
    extract_root: Path,
    excludes: list[str] | None = None,
    tar_cwd: str | None = None,
    timeout: int = 600,
) -> int:
    """ssh tar -czf X.tar.gz → scp_from → local untar。

    rel_paths: paths relative to ``tar_cwd``(forward slash 接). tar_cwd:
    远端 tar 工作目录,default ``REMOTE_ROOT_WIN``;legacy 用 ``<root>\\artifacts``
    让 tar 内部 path 是 ``<run>/...`` 而非 ``artifacts/<run>/...``。excludes:
    tar ``--exclude`` patterns(空 = 不排除)。extract_root: 本地 untar 目标。
    tar 文件本身始终写到 ``REMOTE_ROOT_WIN``,与 cwd 解耦,scp_from + cleanup 路径不变。
    """
    cwd = tar_cwd if tar_cwd is not None else REMOTE_ROOT_WIN
    remote_tar = f'pull_{uuid.uuid4().hex[:8]}.tar.gz'
    tar_abs = f'{REMOTE_ROOT_WIN}\\{remote_tar}'
    paths_arg = ' '.join(ps_quote(p) for p in rel_paths)
    excl_args = ''.join(f' --exclude={ps_quote(e)}' for e in (excludes or []))
    ps = f'cd {ps_quote(cwd)}; tar -czf {ps_quote(tar_abs)}{excl_args} {paths_arg}'
    print(f'[pull] remote tar: {len(rel_paths)} path(s) → {remote_tar}')
    r = ssh_run(ps, timeout=timeout)
    if r.returncode != 0:
        print(f'[pull] remote tar failed: {r.stderr.strip()}', file=sys.stderr)
        return r.returncode
    with tempfile.NamedTemporaryFile(suffix='.tar.gz', delete=False) as fh:
        tar_path = Path(fh.name)
    try:
        r = scp_from(remote_tar, tar_path, timeout=timeout)
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
        ssh_run(
            f'Remove-Item {ps_quote(f"{REMOTE_ROOT_WIN}\\{remote_tar}")} -Force -ErrorAction SilentlyContinue',
            timeout=30,
        )


def _run_legacy(args) -> int:
    excludes = [] if args.all_ckpts else ['ckpts/ckpt_*.pt', 'ckpts/gauntlet_*.pt']
    return _pull_via_tar(
        [args.run_label],
        extract_root=Path(args.local_root),
        excludes=excludes,
        tar_cwd=f'{REMOTE_ROOT_WIN}\\artifacts',
    )


def _run_dir(args) -> int:
    rel = _to_rel(args.dir_.rstrip('/'))
    dst = _local_mirror(args.dir_, args.local_root)
    return _pull_via_tar([rel], extract_root=dst.parent)


def _resolve_glob(glob: str) -> list[str]:
    """ssh PS ``Get-ChildItem`` 解析 glob → REMOTE_ROOT_POSIX-relative paths。"""
    abs_glob = glob if ':' in glob else f'{REMOTE_ROOT_POSIX}/{glob.lstrip("/")}'
    ps = f'Get-ChildItem -Path {ps_quote(abs_glob)} -File | Select-Object -ExpandProperty FullName'
    r = ssh_run(ps)
    if r.returncode != 0:
        raise RuntimeError(f'remote glob ls failed: {r.stderr.strip()}')
    abs_paths = [ln.strip() for ln in r.stdout.splitlines() if ln.strip()]
    return [_to_rel(p) for p in abs_paths]


def _run_files(args) -> int:
    try:
        rel_paths = _resolve_glob(args.files)
    except (RuntimeError, ValueError) as e:
        print(f'error: {e}', file=sys.stderr)
        return 1
    if not rel_paths:
        print(f'error: no remote files matched glob: {args.files}', file=sys.stderr)
        return 1
    dst = _local_mirror(args.files, args.local_root).parent
    return _pull_via_tar(rel_paths, extract_root=dst)


def main():
    args = _build_parser().parse_args()
    provided = sum(x is not None for x in [args.run_label, args.dir_, args.files])
    if provided != 1:
        print('error: exactly one of: <run-label> | --dir | --files required', file=sys.stderr)
        return 2
    if args.run_label:
        return _run_legacy(args)
    if args.dir_:
        return _run_dir(args)
    return _run_files(args)


if __name__ == '__main__':
    sys.exit(main())
