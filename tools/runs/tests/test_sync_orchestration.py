"""Tests for ``tools.runs.sync`` orchestration layer — ``sync()`` driver,
``main()`` CLI, and the ``python -m tools.runs.sync`` subprocess smoke.

Split out of the original 614-line test_sync_pattern.py (T-18 fix-up C-1).
Mock-only (no real rsync / ssh) — T-20 covers the integration tier.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs import sync
from tools.runs.tests._sync_fixtures import (
    FakeResult,
    empty_ssh_runner,
    make_run_dir,
    mock_runner,
    ssh_runner_returning,
)


# ---------------------------------------------------------------------------
# sync() — orchestration (mock both rsync runner + ssh runner)
# ---------------------------------------------------------------------------


def test_sync_push_dry_run_returns_cmd(tmp_path):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=empty_ssh_runner,
        dry_run=True,
    )
    assert isinstance(cmd, list)
    assert cmd[0] == 'rsync'
    assert 'u@h:/p/' in cmd
    assert f'{tmp_path}/' in cmd


def test_sync_push_invokes_runner_when_not_dry(tmp_path):
    captured: list[list[str]] = []
    rc = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        runner=mock_runner(captured),
        ssh_runner=empty_ssh_runner,
    )
    assert rc == 0
    assert len(captured) == 1
    assert captured[0][0] == 'rsync'


def test_sync_creates_local_artifacts_dir(tmp_path):
    captured: list[list[str]] = []
    sync.sync(
        direction='pull',
        remote='u@h:/p/',
        root=tmp_path,
        runner=mock_runner(captured),
        ssh_runner=empty_ssh_runner,
    )
    assert (tmp_path / 'artifacts').exists()


def test_sync_push_local_newer_includes_normally(tmp_path):
    """Local has NNN with newer ts → no exclude added; rsync transfers it."""
    make_run_dir(tmp_path, '202605180200', '000001', 'az', '2026-05-18T02:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=ssh_runner_returning({'000001': '2026-05-18T01:00:00Z'}),
        dry_run=True,
    )
    assert '--exclude=artifacts/*_000001_*/' not in cmd


def test_sync_push_remote_newer_skips_and_warns(tmp_path, capsys):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=ssh_runner_returning({'000001': '2026-05-18T02:00:00Z'}),
        dry_run=True,
    )
    assert '--exclude=artifacts/*_000001_*/' in cmd
    err = capsys.readouterr().err
    assert 'skipping NNN 000001' in err
    assert 'remote_newer' in err


def test_sync_equal_timestamp_raises_conflict(tmp_path):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    with pytest.raises(sync.SyncConflict, match='000001'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=ssh_runner_returning({'000001': '2026-05-18T01:00:00Z'}),
            dry_run=True,
        )


def test_sync_equal_timestamp_lists_multiple_conflicts(tmp_path):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    make_run_dir(tmp_path, '202605180200', '000002', 'dmc', '2026-05-18T02:00:00Z')
    with pytest.raises(sync.SyncConflict) as exc_info:
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=ssh_runner_returning({'000001': '2026-05-18T01:00:00Z', '000002': '2026-05-18T02:00:00Z'}),
            dry_run=True,
        )
    msg = str(exc_info.value)
    assert '000001' in msg
    assert '000002' in msg


def test_sync_pull_local_newer_skips_and_warns(tmp_path, capsys):
    make_run_dir(tmp_path, '202605180200', '000001', 'az', '2026-05-18T02:00:00Z')
    cmd = sync.sync(
        direction='pull',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=ssh_runner_returning({'000001': '2026-05-18T01:00:00Z'}),
        dry_run=True,
    )
    assert '--exclude=artifacts/*_000001_*/' in cmd
    err = capsys.readouterr().err
    assert 'local_newer' in err


def test_sync_only_local_no_warn(tmp_path, capsys):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=empty_ssh_runner,
        dry_run=True,
    )
    err = capsys.readouterr().err
    assert 'skipping' not in err


def test_sync_only_remote_no_warn_on_pull(tmp_path, capsys):
    sync.sync(
        direction='pull',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=ssh_runner_returning({'000099': '2026-05-18T01:00:00Z'}),
        dry_run=True,
    )
    err = capsys.readouterr().err
    assert 'skipping' not in err


def test_sync_rsync_failure_propagates(tmp_path):
    fail = FakeResult(returncode=23, stderr='rsync: receiver failed')
    runner = mock_runner([], fail)
    with pytest.raises(RuntimeError, match='exit 23'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            runner=runner,
            ssh_runner=empty_ssh_runner,
        )


def test_sync_missing_rsync_binary(tmp_path):
    def runner(*_a, **_kw):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'rsync'")

    with pytest.raises(RuntimeError, match='rsync not found'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            runner=runner,
            ssh_runner=empty_ssh_runner,
        )


def test_sync_ssh_failure_treated_as_empty_remote(tmp_path):
    """SSH down → empty remote set → no conflicts; rsync proceeds normally."""

    def failing_ssh(_cmd, **_kw):
        return FakeResult(returncode=255, stderr='ssh: connect failed')

    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=failing_ssh,
        dry_run=True,
    )
    assert isinstance(cmd, list)
    # No conflict-derived exclude because remote scan was empty.
    assert '--exclude=artifacts/*_000001_*/' not in cmd


def test_sync_ssh_filenotfound_treated_as_empty(tmp_path):
    def ssh_missing(_cmd, **_kw):
        raise FileNotFoundError('ssh not on PATH')

    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=ssh_missing,
        dry_run=True,
    )
    assert isinstance(cmd, list)


# ---------------------------------------------------------------------------
# CLI integration (subprocess + module entry point)
# ---------------------------------------------------------------------------


def test_main_dry_run_prints_cmd(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(sync, '_scan_remote_timestamps', lambda *_a, **_kw: {})
    rc = sync.main(['push', 'u@h:/p/', '--root', str(tmp_path), '--dry-run'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'rsync' in out
    assert 'u@h:/p/' in out


def test_main_bad_remote_exits_1(tmp_path, capsys):
    rc = sync.main(['push', 'not-a-remote', '--root', str(tmp_path)])
    assert rc == 1
    assert 'tools.runs.sync' in capsys.readouterr().err


def test_main_invokes_rsync_via_monkeypatched_subprocess(tmp_path, monkeypatch, capsys):
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, 'run', mock_runner(captured, FakeResult(stdout='sent 5 bytes\n')))
    monkeypatch.setattr(sync, '_scan_remote_timestamps', lambda *_a, **_kw: {})
    rc = sync.main(['pull', 'u@h:/p/', '--root', str(tmp_path)])
    assert rc == 0
    assert len(captured) == 1
    assert 'sent 5 bytes' in capsys.readouterr().out


def test_main_subprocess_module_dispatch(tmp_path):
    """Smoke: ``python -m tools.runs.sync push <remote> --dry-run`` runs and
    exits 0 with no real rsync invocation."""
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'tools.runs.sync',
            'push',
            'u@h:/p/',
            '--root',
            str(tmp_path),
            '--dry-run',
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert result.returncode == 0, result.stderr
    assert 'rsync' in result.stdout
