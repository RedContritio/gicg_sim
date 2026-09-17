"""Tests for ``tools.runs.sync`` — pure-function layer (RSYNC_FLAGS +
URL regex + build_rsync_cmd + detect_conflicts + regression guard).

Split out of the original 614-line file (T-18 fix-up C-1) so each test
module fits the 500-line pre-commit hook budget. Scan / orchestration /
CLI tests live in ``test_sync_scan.py`` + ``test_sync_orchestration.py``.

Covers spec §Cross-host sync 设计 / §Conflict resolution HIGH-2-E /
§Include / exclude pattern. Mock-only — real rsync + ssh integration is
T-20 scope.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.runs import sync


# ---------------------------------------------------------------------------
# RSYNC_FLAGS — include + exclude ordering (spec §Include / exclude pattern)
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
# Remote URL regex (T-18 strict — IPv6 + optional user accepted)
# ---------------------------------------------------------------------------


def test_remote_url_user_at_host_abs_path_ok(tmp_path):
    cmd = sync.build_rsync_cmd('push', 'user@host:/path/', root=tmp_path)
    assert cmd[0] == 'rsync'


def test_remote_url_user_at_host_relpath_ok(tmp_path):
    cmd = sync.build_rsync_cmd('push', 'user@host:relpath/', root=tmp_path)
    assert cmd[0] == 'rsync'


def test_remote_url_rejects_no_colon(tmp_path):
    with pytest.raises(ValueError, match=r'\[user@\]host'):
        sync.build_rsync_cmd('push', 'no-colon-remote', root=tmp_path)


def test_remote_url_rejects_no_trailing_slash(tmp_path):
    with pytest.raises(ValueError, match=r'\[user@\]host'):
        sync.build_rsync_cmd('push', 'user@host:/path', root=tmp_path)


def test_remote_url_accepts_no_user(tmp_path):
    cmd = sync.build_rsync_cmd('push', 'host:/path/', root=tmp_path)
    assert cmd[0] == 'rsync'


def test_remote_url_rejects_macos_local_path_with_colon(tmp_path):
    """macOS ``/Volumes/X:/foo/`` contains ``:`` but is local — reject."""
    with pytest.raises(ValueError, match=r'\[user@\]host'):
        sync.build_rsync_cmd('push', '/Volumes/X:/foo/', root=tmp_path)


def test_remote_url_accepts_ipv6_form(tmp_path):
    """IPv6 ``user@[::1]:/path/`` is now accepted (T-19 spec §HIGH-6-B).
    Detailed IPv6 cases live in ``test_sync_ipv6.py``."""
    cmd = sync.build_rsync_cmd('push', 'user@[::1]:/path/', root=tmp_path)
    assert cmd[0] == 'rsync'


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
# Schema-retire regression — old artifacts/runs/*.toml MUST NOT be referenced
# ---------------------------------------------------------------------------


def test_module_does_not_reference_retired_runs_dir():
    """Belt-and-braces: source code MUST NOT contain the retired
    ``artifacts/runs/`` path that pre-redesign sync used."""
    src = Path(sync.__file__).read_text()
    assert 'artifacts/runs/' not in src
