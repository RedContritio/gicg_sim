# Phase A · `tools/remote/` 远程 infra(Task 1-4)

> 父索引:`README.md`。本文件包含 Task 1-4。先 Task 1 → 2 → 3 → 4 顺序执行,每 Task 一个 commit。

---

## Task 1: `tools/remote/_common.py` — ssh / scp / 引用 helpers

**Files:**
- Create: `tools/remote/__init__.py`(空)
- Create: `tools/remote/_common.py`

- [ ] **Step 1: 建目录 + 空 `__init__.py`**

```bash
mkdir -p tools/remote && : > tools/remote/__init__.py
```

- [ ] **Step 2: 写 `_common.py`**

```python
"""tools/remote infra — paradigm-agnostic ssh/scp helpers for the
Windows GPU box(dev@192.0.2.10 / D:\\gicg_dev)."""

from __future__ import annotations

import subprocess
from pathlib import Path

REMOTE = 'dev@192.0.2.10'
REMOTE_ROOT_WIN = r'D:\gicg_dev'
REMOTE_ROOT_POSIX = '/d/gicg_dev'

DEFAULT_SSH_TIMEOUT = 60


def ssh_run(ps_script: str, timeout: int = DEFAULT_SSH_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a PowerShell snippet on remote via ssh. stderr decode='replace'(cp936)."""
    cmd = ['ssh', REMOTE, 'powershell', '-ExecutionPolicy', 'Bypass', '-Command', ps_script]
    return subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout)


def scp_to(local: Path, remote_rel: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Local → Windows. `remote_rel` relative to REMOTE_ROOT_POSIX."""
    dst = f'{REMOTE}:{REMOTE_ROOT_POSIX}/{remote_rel}'
    return subprocess.run(['scp', '-q', str(local), dst],
                          capture_output=True, text=True, errors='replace', timeout=timeout)


def scp_from(remote_rel: str, local: Path, timeout: int = 120) -> subprocess.CompletedProcess:
    """Windows → Local."""
    src = f'{REMOTE}:{REMOTE_ROOT_POSIX}/{remote_rel}'
    return subprocess.run(['scp', '-q', src, str(local)],
                          capture_output=True, text=True, errors='replace', timeout=timeout)


def ps_quote(s: str) -> str:
    """Single-quote for PowerShell。"""
    return "'" + s.replace("'", "''") + "'"
```

- [ ] **Step 3: Smoke**

Run: `.venv/bin/python -c "from tools.remote import _common; print(_common.REMOTE)"`
Expected: `dev@192.0.2.10`

- [ ] **Step 4: Commit**

```bash
git add tools/remote/__init__.py tools/remote/_common.py
git commit -m "tools/remote: add _common.py (ssh/scp helpers, Windows GPU box constants)"
```

---

## Task 2: `tools/remote/run.py` — Windows 模块 entry 包装

**Files:**
- Create: `tools/remote/run.py`

- [ ] **Step 1: 写 `run.py`**

```python
"""Run a Python module on Windows GPU box via ssh.

Usage::

    .venv/bin/python -m tools.remote.run -- python -m tools.dmc_train configs/dmc_stage3_pilot.toml

`--` 分割 wrapper 参数与远程命令。PS prelude 设 OMP/MKL/PYTHONIOENCODING/PYTHONUNBUFFERED。"""

from __future__ import annotations

import argparse
import shlex
import sys

from tools.remote._common import REMOTE, REMOTE_ROOT_WIN, ssh_run


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--cwd', default=REMOTE_ROOT_WIN)
    p.add_argument('--timeout', type=int, default=86400, help='default 1 day')
    p.add_argument('cmd', nargs=argparse.REMAINDER)
    args = p.parse_args()
    if not args.cmd:
        p.error('no command given (use -- to separate)')
    raw = ' '.join(shlex.quote(c) for c in args.cmd if c != '--')
    ps = (
        '$env:OMP_NUM_THREADS=1; $env:MKL_NUM_THREADS=1; '
        '$env:PYTHONIOENCODING="utf-8"; $env:PYTHONUNBUFFERED=1; '
        f'cd "{args.cwd}"; {raw}'
    )
    print(f'[remote.run] {REMOTE} >> {raw}')
    r = ssh_run(ps, timeout=args.timeout)
    if r.stdout:
        sys.stdout.write(r.stdout)
    if r.stderr:
        sys.stderr.write(r.stderr)
    return r.returncode


if __name__ == '__main__':
    sys.exit(main())
```

- [ ] **Step 2: Smoke — 跑无副作用命令**

Run: `.venv/bin/python -m tools.remote.run -- python --version`
Expected: 打印 Windows 端 Python 版本,exit 0。

- [ ] **Step 3: Commit**

```bash
git add tools/remote/run.py
git commit -m "tools/remote: add run.py — wrap ssh+powershell module entry"
```

---

## Task 3: `tools/remote/sync.py` — Mac → Windows 同步

**Files:**
- Create: `tools/remote/sync.py`

- [ ] **Step 1: 写 `sync.py`**

```python
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
```

- [ ] **Step 2: Smoke — git-changed**

Run: `.venv/bin/python -m tools.remote.sync --git-changed`
Expected: 列出 N 文件,scp + remote untar,exit 0。

- [ ] **Step 3: Commit**

```bash
git add tools/remote/sync.py
git commit -m "tools/remote: add sync.py (--single / --tar-all / --git-changed)"
```

---

## Task 4: rename `dmc_win_status.py` → `tools/remote/status.py` + `dmc_status.ps1` → `tools/remote/status.ps1`

**Files:**
- Move: `tools/dmc_win_status.py` → `tools/remote/status.py`
- Move: `tools/dmc_status.ps1` → `tools/remote/status.ps1`
- Modify: 新 `tools/remote/status.py` 顶部 `PS_SCRIPT_PATH` 与 docstring

- [ ] **Step 1: git mv**

```bash
git mv tools/dmc_win_status.py tools/remote/status.py
git mv tools/dmc_status.ps1 tools/remote/status.ps1
```

- [ ] **Step 2: 编辑 `tools/remote/status.py`**

- 改 line 33:`PS_SCRIPT_PATH = r'D:\gicg_dev\tools\dmc_status.ps1'` → `PS_SCRIPT_PATH = r'D:\gicg_dev\tools\remote\status.ps1'`
- module docstring usage 行从 `tools.dmc_win_status` → `tools.remote.status`(line 12, 15, 18)
- (可选)`ssh_query()` 可改用 `tools.remote._common.ssh_run` 但本 task 不强制。

- [ ] **Step 3: Sync ps1 到 Windows(新路径)**

Run: `.venv/bin/python -m tools.remote.sync --single tools/remote/status.ps1`
Expected: exit 0(Windows 端 `D:\gicg_dev\tools\remote\status.ps1` 就位)。

- [ ] **Step 4: Smoke**

Run: `.venv/bin/python -m tools.remote.status`
Expected: 打印 `== run: ...` + GPU/CPU/MEM/episode/eval 行(或 `===RUN===(none)` 时 fallback ok)。

- [ ] **Step 5: Commit**

```bash
git add tools/remote/status.py tools/remote/status.ps1
git commit -m "tools/remote: rename dmc_win_status → remote/status (paradigm-agnostic location)"
```
