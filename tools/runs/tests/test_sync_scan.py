"""Tests for ``tools.runs.sync`` scan layer —
``_scan_local_timestamps`` + ``_parse_remote_find_output``.

Split out of the original 614-line test_sync_pattern.py (T-18 fix-up C-1).
Mock-only — real SSH integration is T-20 scope.
"""

from __future__ import annotations

from tools.runs import sync
from tools.runs.tests._sync_fixtures import make_run_dir


# ---------------------------------------------------------------------------
# _scan_local_timestamps
# ---------------------------------------------------------------------------


def test_scan_local_timestamps_picks_up_run_dirs(tmp_path):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    make_run_dir(tmp_path, '202605180200', '000002', 'dmc', '2026-05-18T02:00:00Z')
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


# ---------------------------------------------------------------------------
# _parse_remote_find_output
# ---------------------------------------------------------------------------


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
