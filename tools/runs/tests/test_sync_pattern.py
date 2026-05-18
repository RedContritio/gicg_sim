"""Tests for ``tools.runs.sync`` — T-18 clean-slate redesign.

Covers spec §Cross-host sync 设计 / §Conflict resolution HIGH-2-E /
§Include / exclude pattern. Mock-only — real rsync + ssh integration is
T-20 scope.
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from tools.runs import sync


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: str = ''
    stderr: str = ''


def _mock_runner(captured: list[list[str]], result: FakeResult = FakeResult()):
    """Return a fake ``subprocess.run`` that captures argv into ``captured``."""

    def runner(cmd, capture_output=False, text=False, check=False, **kw):
        captured.append(list(cmd))
        return result

    return runner


def _empty_ssh_runner(_cmd, **_kw):
    """SSH find returning empty (no remote runs) — never raises."""
    return FakeResult(returncode=0, stdout='')


def _make_run_dir(root: Path, ts_prefix: str, nnn: str, label: str, timestamp_field: str) -> Path:
    """Create ``<root>/artifacts/<ts_prefix>_<nnn>_<label>/metadata.toml``
    with all 11 required schema fields (only ``timestamp`` matters for tests)."""
    run_dir = root / 'artifacts' / f'{ts_prefix}_{nnn}_{label}'
    run_dir.mkdir(parents=True)
    # Minimal schema-valid TOML body — only timestamp is consulted by sync;
    # the rest is for forward-compat if a future test wires through
    # schema.load_file (not used today).
    body = (
        f'run_id = "{nnn}"\n'
        f'timestamp = "{timestamp_field}"\n'
        'cfg_file = "configs/x.toml"\n'
        'cfg_resolved_version = 1\n'
        'git_commit = "deadbeef"\n'
        'host = "h"\n'
        'status = "done"\n'
        f'artifacts_dir = "artifacts/{ts_prefix}_{nnn}_{label}"\n'
        'wall_seconds = 0.0\n'
        'exit_code = 0\n'
        'notes = ""\n'
    )
    (run_dir / 'metadata.toml').write_text(body)
    return run_dir


def _ssh_runner_returning(remote_runs: dict[str, str]):
    """Build an SSH runner that emits the ``===FILE / ===END`` blocks
    expected by ``_parse_remote_find_output``."""

    def runner(_cmd, **_kw):
        blocks: list[str] = []
        for nnn, ts in remote_runs.items():
            file_path = f'artifacts/202605180000_{nnn}_remote/metadata.toml'
            body = (
                f'run_id = "{nnn}"\n'
                f'timestamp = "{ts}"\n'
                'cfg_file = "x"\n'
                'cfg_resolved_version = 1\n'
                'git_commit = "x"\n'
                'host = "h"\n'
                'status = "done"\n'
                f'artifacts_dir = "artifacts/202605180000_{nnn}_remote"\n'
                'wall_seconds = 0.0\n'
                'exit_code = 0\n'
                'notes = ""\n'
            )
            blocks.append(f'===FILE {file_path}\n{body}\n===END\n')
        return FakeResult(returncode=0, stdout=''.join(blocks))

    return runner


# ---------------------------------------------------------------------------
# RSYNC_FLAGS — include + exclude ordering (spec 行 357-371)
# ---------------------------------------------------------------------------


def test_rsync_flags_include_pattern_present():
    flags = sync.RSYNC_FLAGS
    assert '--include=artifacts/' in flags
    assert '--include=artifacts/*/' in flags
    assert '--include=artifacts/*/metadata.toml' in flags
    assert '--include=artifacts/*/cfg_resolved*.toml' in flags
    assert '--include=artifacts/*/cfg_leaf*.toml' in flags


def test_rsync_flags_exclude_pattern_present():
    flags = sync.RSYNC_FLAGS
    assert '--exclude=artifacts/.authoritative_host' in flags
    assert '--exclude=artifacts/.run_id_lock' in flags
    assert '--exclude=artifacts/*/.metadata_lock' in flags
    assert '--exclude=*' in flags


def test_rsync_flags_no_old_runs_dir_pattern():
    """Pre-redesign ``artifacts/runs/*.toml`` is retired — flags MUST NOT
    reference it."""
    joined = ' '.join(sync.RSYNC_FLAGS)
    assert 'artifacts/runs/' not in joined


def test_rsync_flags_excludes_ckpts_and_metrics_implicitly():
    """``ckpts/`` / ``metrics.jsonl`` / ``tb/`` are not explicitly listed
    but the ``--exclude=*`` tail catches them. Guard against any future
    addition that would name them in an include."""
    joined = ' '.join(sync.RSYNC_FLAGS)
    assert 'ckpts' not in joined
    assert 'metrics.jsonl' not in joined
    assert '--include=artifacts/*/tb' not in joined


def test_rsync_flags_exclude_strict_order():
    """Order matters: rsync first-match-wins. The strict order is
    host-local excludes BEFORE the catch-all ``*`` exclude."""
    flags = list(sync.RSYNC_FLAGS)
    i_auth = flags.index('--exclude=artifacts/.authoritative_host')
    i_runlock = flags.index('--exclude=artifacts/.run_id_lock')
    i_metalock = flags.index('--exclude=artifacts/*/.metadata_lock')
    i_star = flags.index('--exclude=*')
    assert i_auth < i_star
    assert i_runlock < i_star
    assert i_metalock < i_star


# ---------------------------------------------------------------------------
# Remote URL regex (T-18 strict — IPv6 + bare host rejected)
# ---------------------------------------------------------------------------


def test_remote_url_user_at_host_abs_path_ok(tmp_path):
    cmd = sync.build_rsync_cmd('push', 'user@host:/path/', root=tmp_path)
    assert cmd[0] == 'rsync'


def test_remote_url_user_at_host_relpath_ok(tmp_path):
    cmd = sync.build_rsync_cmd('push', 'user@host:relpath/', root=tmp_path)
    assert cmd[0] == 'rsync'


def test_remote_url_rejects_no_colon(tmp_path):
    with pytest.raises(ValueError, match='user@host'):
        sync.build_rsync_cmd('push', 'no-colon-remote', root=tmp_path)


def test_remote_url_rejects_no_trailing_slash(tmp_path):
    with pytest.raises(ValueError, match='user@host'):
        sync.build_rsync_cmd('push', 'user@host:/path', root=tmp_path)


def test_remote_url_rejects_no_user(tmp_path):
    with pytest.raises(ValueError, match='user@host'):
        sync.build_rsync_cmd('push', 'host:/path/', root=tmp_path)


def test_remote_url_rejects_macos_local_path_with_colon(tmp_path):
    """macOS ``/Volumes/X:/foo/`` contains ``:`` but is local — reject."""
    with pytest.raises(ValueError, match='user@host'):
        sync.build_rsync_cmd('push', '/Volumes/X:/foo/', root=tmp_path)


def test_remote_url_rejects_ipv6_form(tmp_path):
    """IPv6 ``user@[::1]:/path/`` is T-19 scope — explicitly rejected for T-18."""
    with pytest.raises(ValueError, match='user@host'):
        sync.build_rsync_cmd('push', 'user@[::1]:/path/', root=tmp_path)


# ---------------------------------------------------------------------------
# build_rsync_cmd — direction + arg order + conflict excludes
# ---------------------------------------------------------------------------


def test_build_rsync_cmd_push_local_before_remote(tmp_path):
    cmd = sync.build_rsync_cmd('push', 'u@h:/p/', root=tmp_path)
    local_arg = f'{tmp_path}/'
    remote_arg = 'u@h:/p/'
    assert cmd.index(local_arg) < cmd.index(remote_arg)


def test_build_rsync_cmd_pull_remote_before_local(tmp_path):
    cmd = sync.build_rsync_cmd('pull', 'u@h:/p/', root=tmp_path)
    local_arg = f'{tmp_path}/'
    remote_arg = 'u@h:/p/'
    assert cmd.index(remote_arg) < cmd.index(local_arg)


def test_build_rsync_cmd_rejects_bad_direction(tmp_path):
    with pytest.raises(ValueError, match='push|pull'):
        sync.build_rsync_cmd('sideways', 'u@h:/p/', root=tmp_path)


def test_build_rsync_cmd_conflict_excludes_come_before_includes(tmp_path):
    """Conflict excludes must precede include rules so rsync first-match-wins."""
    rows = [sync.ConflictRow(nnn='000042', local_ts='a', remote_ts='b', resolution='remote_newer')]
    cmd = sync.build_rsync_cmd('push', 'u@h:/p/', root=tmp_path, conflict_rows=rows)
    excl_idx = cmd.index('--exclude=artifacts/*_000042_*/')
    incl_idx = cmd.index('--include=artifacts/*/metadata.toml')
    assert excl_idx < incl_idx


def test_build_rsync_cmd_push_excludes_remote_newer(tmp_path):
    rows = [
        sync.ConflictRow(nnn='000001', local_ts='a', remote_ts='b', resolution='remote_newer'),
        sync.ConflictRow(nnn='000002', local_ts='c', remote_ts='b', resolution='local_newer'),
        sync.ConflictRow(nnn='000003', local_ts='c', remote_ts=None, resolution='only_local'),
    ]
    cmd = sync.build_rsync_cmd('push', 'u@h:/p/', root=tmp_path, conflict_rows=rows)
    assert '--exclude=artifacts/*_000001_*/' in cmd  # remote_newer → exclude
    assert '--exclude=artifacts/*_000002_*/' not in cmd  # local_newer → push OK
    assert '--exclude=artifacts/*_000003_*/' not in cmd  # only_local → push OK


def test_build_rsync_cmd_pull_excludes_local_newer(tmp_path):
    rows = [
        sync.ConflictRow(nnn='000001', local_ts='a', remote_ts='b', resolution='remote_newer'),
        sync.ConflictRow(nnn='000002', local_ts='c', remote_ts='b', resolution='local_newer'),
    ]
    cmd = sync.build_rsync_cmd('pull', 'u@h:/p/', root=tmp_path, conflict_rows=rows)
    assert '--exclude=artifacts/*_000002_*/' in cmd  # local_newer → exclude on pull
    assert '--exclude=artifacts/*_000001_*/' not in cmd  # remote_newer → pull OK


# ---------------------------------------------------------------------------
# detect_conflicts — pure function
# ---------------------------------------------------------------------------


def test_detect_conflicts_local_newer():
    rows = sync.detect_conflicts({'000001': '2026-05-18T01:00:00Z'}, {'000001': '2026-05-17T01:00:00Z'})
    assert len(rows) == 1
    assert rows[0].resolution == 'local_newer'
    assert rows[0].nnn == '000001'


def test_detect_conflicts_remote_newer():
    rows = sync.detect_conflicts({'000001': '2026-05-17T00:00:00Z'}, {'000001': '2026-05-18T00:00:00Z'})
    assert rows[0].resolution == 'remote_newer'


def test_detect_conflicts_equal():
    rows = sync.detect_conflicts({'000001': '2026-05-18T00:00:00Z'}, {'000001': '2026-05-18T00:00:00Z'})
    assert rows[0].resolution == 'equal'


def test_detect_conflicts_only_local_not_conflict():
    rows = sync.detect_conflicts({'000001': '2026-05-18T00:00:00Z'}, {})
    assert rows[0].resolution == 'only_local'


def test_detect_conflicts_only_remote_not_conflict():
    rows = sync.detect_conflicts({}, {'000001': '2026-05-18T00:00:00Z'})
    assert rows[0].resolution == 'only_remote'


def test_detect_conflicts_sorted_by_nnn():
    rows = sync.detect_conflicts(
        {'000003': 'a', '000001': 'b'},
        {'000002': 'c'},
    )
    assert [r.nnn for r in rows] == ['000001', '000002', '000003']


# ---------------------------------------------------------------------------
# _scan_local_timestamps + _parse_remote_find_output
# ---------------------------------------------------------------------------


def test_scan_local_timestamps_picks_up_run_dirs(tmp_path):
    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    _make_run_dir(tmp_path, '202605180200', '000002', 'dmc', '2026-05-18T02:00:00Z')
    out = sync._scan_local_timestamps(tmp_path)
    assert out == {
        '000001': '2026-05-18T01:00:00Z',
        '000002': '2026-05-18T02:00:00Z',
    }


def test_scan_local_timestamps_skips_non_run_dirs(tmp_path):
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'artifacts' / 'pre_redesign_x').mkdir()
    (tmp_path / 'artifacts' / 'pre_redesign_x' / 'metadata.toml').write_text('timestamp = "x"\n')
    out = sync._scan_local_timestamps(tmp_path)
    assert out == {}


def test_scan_local_timestamps_skips_missing_metadata(tmp_path):
    (tmp_path / 'artifacts' / '202605180100_000001_x').mkdir(parents=True)
    out = sync._scan_local_timestamps(tmp_path)
    assert out == {}


def test_scan_local_timestamps_skips_malformed(tmp_path):
    bad = tmp_path / 'artifacts' / '202605180100_000001_x'
    bad.mkdir(parents=True)
    (bad / 'metadata.toml').write_text('not valid TOML = =')
    out = sync._scan_local_timestamps(tmp_path)
    assert out == {}


def test_scan_local_timestamps_no_artifacts_dir(tmp_path):
    assert sync._scan_local_timestamps(tmp_path) == {}


def test_parse_remote_find_output_extracts_timestamps():
    payload = (
        '===FILE artifacts/202605180100_000001_az/metadata.toml\n'
        'timestamp = "2026-05-18T01:00:00Z"\n'
        '\n===END\n'
        '===FILE artifacts/202605180200_000002_dmc/metadata.toml\n'
        'timestamp = "2026-05-18T02:00:00Z"\n'
        '\n===END\n'
    )
    out = sync._parse_remote_find_output(payload)
    assert out == {
        '000001': '2026-05-18T01:00:00Z',
        '000002': '2026-05-18T02:00:00Z',
    }


def test_parse_remote_find_output_skips_unknown_blocks():
    payload = '===FILE artifacts/some_legacy_dir/metadata.toml\ntimestamp = "old"\n\n===END\n'
    out = sync._parse_remote_find_output(payload)
    assert out == {}


# ---------------------------------------------------------------------------
# sync() — orchestration (mock both rsync runner + ssh runner)
# ---------------------------------------------------------------------------


def test_sync_push_dry_run_returns_cmd(tmp_path):
    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=_empty_ssh_runner,
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
        runner=_mock_runner(captured),
        ssh_runner=_empty_ssh_runner,
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
        runner=_mock_runner(captured),
        ssh_runner=_empty_ssh_runner,
    )
    assert (tmp_path / 'artifacts').exists()


def test_sync_push_local_newer_includes_normally(tmp_path):
    """Local has NNN with newer ts → no exclude added; rsync transfers it."""
    _make_run_dir(tmp_path, '202605180200', '000001', 'az', '2026-05-18T02:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=_ssh_runner_returning({'000001': '2026-05-18T01:00:00Z'}),
        dry_run=True,
    )
    assert '--exclude=artifacts/*_000001_*/' not in cmd


def test_sync_push_remote_newer_skips_and_warns(tmp_path, capsys):
    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=_ssh_runner_returning({'000001': '2026-05-18T02:00:00Z'}),
        dry_run=True,
    )
    assert '--exclude=artifacts/*_000001_*/' in cmd
    err = capsys.readouterr().err
    assert 'skipping NNN 000001' in err
    assert 'remote_newer' in err


def test_sync_equal_timestamp_raises_conflict(tmp_path):
    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    with pytest.raises(sync.SyncConflict, match='000001'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=_ssh_runner_returning({'000001': '2026-05-18T01:00:00Z'}),
            dry_run=True,
        )


def test_sync_equal_timestamp_lists_multiple_conflicts(tmp_path):
    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    _make_run_dir(tmp_path, '202605180200', '000002', 'dmc', '2026-05-18T02:00:00Z')
    with pytest.raises(sync.SyncConflict) as exc_info:
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=_ssh_runner_returning({'000001': '2026-05-18T01:00:00Z', '000002': '2026-05-18T02:00:00Z'}),
            dry_run=True,
        )
    msg = str(exc_info.value)
    assert '000001' in msg
    assert '000002' in msg


def test_sync_pull_local_newer_skips_and_warns(tmp_path, capsys):
    _make_run_dir(tmp_path, '202605180200', '000001', 'az', '2026-05-18T02:00:00Z')
    cmd = sync.sync(
        direction='pull',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=_ssh_runner_returning({'000001': '2026-05-18T01:00:00Z'}),
        dry_run=True,
    )
    assert '--exclude=artifacts/*_000001_*/' in cmd
    err = capsys.readouterr().err
    assert 'local_newer' in err


def test_sync_only_local_no_warn(tmp_path, capsys):
    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=_empty_ssh_runner,
        dry_run=True,
    )
    err = capsys.readouterr().err
    assert 'skipping' not in err


def test_sync_only_remote_no_warn_on_pull(tmp_path, capsys):
    sync.sync(
        direction='pull',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=_ssh_runner_returning({'000099': '2026-05-18T01:00:00Z'}),
        dry_run=True,
    )
    err = capsys.readouterr().err
    assert 'skipping' not in err


def test_sync_rsync_failure_propagates(tmp_path):
    fail = FakeResult(returncode=23, stderr='rsync: receiver failed')
    runner = _mock_runner([], fail)
    with pytest.raises(RuntimeError, match='exit 23'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            runner=runner,
            ssh_runner=_empty_ssh_runner,
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
            ssh_runner=_empty_ssh_runner,
        )


def test_sync_ssh_failure_treated_as_empty_remote(tmp_path):
    """SSH down → empty remote set → no conflicts; rsync proceeds normally."""

    def failing_ssh(_cmd, **_kw):
        return FakeResult(returncode=255, stderr='ssh: connect failed')

    _make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
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
    monkeypatch.setattr(subprocess, 'run', _mock_runner(captured, FakeResult(stdout='sent 5 bytes\n')))
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


# ---------------------------------------------------------------------------
# Schema-retire regression — old artifacts/runs/*.toml MUST NOT be referenced
# ---------------------------------------------------------------------------


def test_module_does_not_reference_retired_runs_dir():
    """Belt-and-braces: source code MUST NOT contain the retired
    ``artifacts/runs/`` path that pre-redesign sync used."""
    src = Path(sync.__file__).read_text()
    assert 'artifacts/runs/' not in src
