"""Smoke tests for tools.runs.sync — rsync is mocked, never actually invoked."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Any

import pytest

from tools.runs import sync


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: str = ''
    stderr: str = ''


def _mock_runner(captured: list[list[str]], result: FakeResult = FakeResult()):
    """Return a fake subprocess.run that captures the argv into the
    list and returns the supplied result."""

    def runner(cmd, capture_output=False, text=False, check=False, **kw):
        captured.append(list(cmd))
        return result

    return runner


def test_build_command_push_shape(tmp_path):
    cmd = sync.build_command('push', 'dev@host:/d/gicg_dev/', root=tmp_path)
    assert cmd[0] == 'rsync'
    # Local arg should be before remote in push.
    local_idx = cmd.index(f'{tmp_path}/')
    remote_idx = cmd.index('dev@host:/d/gicg_dev/')
    assert local_idx < remote_idx


def test_build_command_pull_shape(tmp_path):
    cmd = sync.build_command('pull', 'dev@host:/d/gicg_dev/', root=tmp_path)
    # Remote arg should be before local in pull.
    local_idx = cmd.index(f'{tmp_path}/')
    remote_idx = cmd.index('dev@host:/d/gicg_dev/')
    assert remote_idx < local_idx


def test_build_command_hardcoded_flags(tmp_path):
    """Spec T4 + risk R6: include/exclude flags MUST be present
    verbatim and SHALL NOT be user-overridable."""
    cmd = sync.build_command('push', 'h:/p/', root=tmp_path)
    assert '-av' in cmd
    assert '--update' in cmd
    assert '--include=artifacts/' in cmd
    assert '--include=artifacts/runs/' in cmd
    assert '--include=artifacts/runs/*.toml' in cmd
    assert '--exclude=*' in cmd


def test_build_command_rejects_bad_direction(tmp_path):
    with pytest.raises(ValueError):
        sync.build_command('sideways', 'h:/p/', root=tmp_path)


def test_build_command_rejects_no_colon():
    with pytest.raises(ValueError, match='colon'):
        sync.build_command('push', 'no-colon-remote')


def test_build_command_rejects_path_without_trailing_slash():
    with pytest.raises(ValueError, match='end with'):
        sync.build_command('push', 'dev@host:/d/gicg_dev')


def test_sync_pull_invokes_rsync_with_expected_argv(tmp_path):
    captured: list[list[str]] = []
    rc = sync.sync(
        direction='pull',
        remote='dev@host:/repo/',
        root=tmp_path,
        runner=_mock_runner(captured),
    )
    assert rc == 0
    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[0] == 'rsync'
    assert 'dev@host:/repo/' in cmd
    assert f'{tmp_path}/' in cmd
    # destination dir must exist after sync (rsync precondition).
    assert (tmp_path / 'artifacts' / 'runs').exists()


def test_sync_push_invokes_rsync_with_expected_argv(tmp_path):
    captured: list[list[str]] = []
    rc = sync.sync(
        direction='push',
        remote='dev@host:/repo/',
        root=tmp_path,
        runner=_mock_runner(captured),
    )
    assert rc == 0
    assert len(captured) == 1


def test_sync_propagates_rsync_failure(tmp_path):
    captured: list[list[str]] = []
    fail = FakeResult(returncode=23, stderr='rsync: receiver failed')
    runner = _mock_runner(captured, fail)
    with pytest.raises(RuntimeError, match='exit 23'):
        sync.sync(
            direction='pull',
            remote='dev@host:/repo/',
            root=tmp_path,
            runner=runner,
        )


def test_sync_handles_missing_rsync_binary(tmp_path):
    def runner(*a, **kw):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'rsync'")

    with pytest.raises(RuntimeError, match='rsync not found'):
        sync.sync(
            direction='pull',
            remote='dev@host:/repo/',
            root=tmp_path,
            runner=runner,
        )


def test_sync_cli_main_happy(tmp_path, monkeypatch, capsys):
    """Patch subprocess.run at module level so the CLI path uses mock."""
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, 'run', _mock_runner(captured, FakeResult(stdout='sent 5 files\n')))
    rc = sync.main(
        [
            'pull',
            'dev@host:/repo/',
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert len(captured) == 1
    assert 'sent 5 files' in capsys.readouterr().out


def test_sync_cli_main_error_bad_remote(tmp_path, capsys):
    rc = sync.main(
        [
            'pull',
            'no-colon',
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 1
    assert 'tools.runs.sync' in capsys.readouterr().err


def test_sync_never_includes_checkpoints_or_replays(tmp_path):
    """Risk R6 regression guard: ckpt + replays MUST NOT leak into the
    rsync argv."""
    cmd = sync.build_command('push', 'h:/p/', root=tmp_path)
    joined = ' '.join(cmd)
    assert 'checkpoints' not in joined
    assert 'replays' not in joined
