"""Real-ssh e2e smoke for tools.runs.* cfg-driven dispatch (post I30 P3).

Opt-in only: ``pytest -m smoke_remote`` — default ``pytest`` deselect。

需要:
- ``configs/dmc/stage3_b_v_legacy.toml`` 完整 [remote] 段(ssh / root /
  os / hostname,本仓库 commit c950cc2 起入仓);
- 远端 Windows GPU box(DESKTOP-GHJCC7Q)在线,key-based ssh 不要 password。

每测试 timeout 防 hang。失败时 print stderr/stdout 给 debug。

This opt-in suite verifies real production transport behavior that mocked
unit tests cannot cover. It previously caught a broken remote kill path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

CFG = 'configs/dmc/stage3_b_v_legacy.toml'
PYTHON = '.venv/bin/python'


def _require_cfg():
    if not Path(CFG).is_file():
        pytest.skip(f'{CFG} missing — run from repo root')


@pytest.mark.smoke_remote
def test_remote_probe_round_trip():
    """Real ssh: discover_remote_python + discover_remote_binary go/gcc all hit。"""
    _require_cfg()
    from tools.runs._host import discover_remote_binary, discover_remote_python, load_remote_from_cfg

    remote = load_remote_from_cfg(Path(CFG))
    assert remote is not None, 'stage3_b_v_legacy.toml expected to have meta.host=remote'

    py = discover_remote_python(remote)
    assert py.endswith('.exe') or py.endswith('python') or py.endswith('python3')

    go = discover_remote_binary(remote, 'go')
    assert 'go' in go.lower()

    gcc = discover_remote_binary(remote, 'gcc')
    assert 'gcc' in gcc.lower()


@pytest.mark.smoke_remote
def test_remote_tail_round_trip():
    """Real ssh: tail D:/gicg_dev/go.mod → 'module gicg_mono' in stdout。"""
    _require_cfg()
    proc = subprocess.run(
        [PYTHON, '-m', 'tools.runs.tail', CFG, 'D:/gicg_dev/go.mod', '--lines', '3'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f'stderr: {proc.stderr}'
    assert 'module gicg_mono' in proc.stdout, f'stdout: {proc.stdout!r}'


@pytest.mark.smoke_remote
def test_remote_kill_dry_run():
    """Real ssh: kill --all --dry-run → exit 0,Get-Process invoked。"""
    _require_cfg()
    proc = subprocess.run(
        [PYTHON, '-m', 'tools.runs.kill', CFG, '--all', '--dry-run'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f'stderr: {proc.stderr}'
    combined = proc.stdout + proc.stderr
    assert 'Get-Process' in combined or 'dry-run' in combined


@pytest.mark.smoke_remote
def test_remote_sync_dry_run():
    """Real ssh: _remote_sync --dry-run → exit 0,候选文件 list 输出。"""
    _require_cfg()
    proc = subprocess.run(
        [PYTHON, '-m', 'tools.runs._remote_sync', CFG, '--dry-run'],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f'stderr: {proc.stderr}'


@pytest.mark.smoke_remote
def test_remote_train_dispatch_invalid_resume_propagates():
    """Real ssh: train.py --resume <bad path> → auto-sync + ssh_forward +
    远端 Phase A fail → 本地 propagate 非 0 exit code,验 dispatch +
    sync + ssh forward + exit-code chain 全链路。"""
    _require_cfg()
    proc = subprocess.run(
        [PYTHON, '-m', 'tools.runs.train', CFG, '--resume', '/nonexistent/path/ckpt.pt'],
        capture_output=True,
        text=True,
        timeout=180,  # auto-sync ~30s + ssh forward + remote Phase A fail ~5s
    )
    # 远端 Phase A 因 nonexistent path 必 raise → exit 1 or 2(setup failed)
    assert proc.returncode != 0, 'expected non-zero exit from remote Phase A failure'
    output = proc.stdout + proc.stderr
    assert '[train.remote]' in output or 'auto-sync' in output.lower() or 'sync' in output.lower(), (
        f'expected auto-sync trace in output;\nstdout: {proc.stdout!r}\nstderr: {proc.stderr!r}'
    )
