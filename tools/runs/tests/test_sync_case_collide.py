"""Tests for case-collide detection in ``tools.runs.sync`` (T-19).

Spec §CRIT-5-A — macOS APFS (case-insensitive default) ↔ Linux
ext4 (case-sensitive default) cross-OS sync can silently overwrite when
two run-dir names differ only by case (``..._DMC`` vs ``..._dmc``).

Defence is a pre-flight scan that raises
:class:`~tools.runs._helpers.sync_extras.CaseCollideError` BEFORE any
rsync invocation, listing every colliding pair so the user can resolve
in one pass.

Three layers:
- :func:`detect_case_collisions` pure function (input → pair list)
- :func:`scan_local_dir_names` / :func:`parse_remote_dir_names` parsers
- ``sync()`` wiring — raise on collision; happy path unaffected
"""

from __future__ import annotations

import pytest

from tools.runs import sync
from tools.runs._helpers import sync_extras
from tools.runs._helpers.sync_scan import (
    parse_remote_dir_names,
    scan_local_dir_names,
)
from tools.runs.tests._sync_fixtures import (
    make_run_dir,
    ssh_runner_returning,
)


# ---------------------------------------------------------------------------
# detect_case_collisions — pure function
# ---------------------------------------------------------------------------


def test_detect_collisions_simple_pair():
    pairs = sync_extras.detect_case_collisions(['DMC', 'dmc'])
    assert pairs == [('DMC', 'dmc')]


def test_detect_collisions_exact_duplicates_are_not_a_collision():
    """Same casing twice = same identifier, not a collision (one dir on disk)."""
    assert sync_extras.detect_case_collisions(['DMC', 'DMC']) == []


def test_detect_collisions_unrelated_names():
    assert sync_extras.detect_case_collisions(['A', 'B', 'C']) == []


def test_detect_collisions_mixed_with_unrelated():
    pairs = sync_extras.detect_case_collisions(['A', 'B', 'a'])
    assert pairs == [('A', 'a')]


def test_detect_collisions_complex_label():
    pairs = sync_extras.detect_case_collisions(['Foo_BAR', 'foo_bar', 'baz'])
    assert pairs == [('Foo_BAR', 'foo_bar')]


def test_detect_collisions_multiple_pairs():
    pairs = sync_extras.detect_case_collisions(['DMC', 'dmc', 'AZ', 'az'])
    assert ('DMC', 'dmc') in pairs
    assert ('AZ', 'az') in pairs
    assert len(pairs) == 2


def test_detect_collisions_empty_list():
    assert sync_extras.detect_case_collisions([]) == []


def test_detect_collisions_single_element():
    assert sync_extras.detect_case_collisions(['only']) == []


def test_detect_collisions_iteration_order_preserved():
    """First-seen wins as the ``a`` of the pair."""
    pairs = sync_extras.detect_case_collisions(['DMC', 'dmc', 'Dmc'])
    # 'dmc' collides with 'DMC' (first seen). 'Dmc' also collides with 'DMC'.
    assert ('DMC', 'dmc') in pairs
    assert ('DMC', 'Dmc') in pairs


def test_collision_error_is_runtime_error():
    """``CaseCollideError`` inherits from ``RuntimeError`` so existing
    ``except RuntimeError`` handlers keep catching it."""
    assert issubclass(sync_extras.CaseCollideError, RuntimeError)


def test_collision_error_re_exported_via_sync_module():
    assert sync.CaseCollideError is sync_extras.CaseCollideError


# ---------------------------------------------------------------------------
# scan_local_dir_names — picks up valid run-dirs only
# ---------------------------------------------------------------------------


def test_scan_local_dir_names_picks_up_run_dirs(tmp_path):
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    make_run_dir(tmp_path, '202605180200', '000002', 'dmc', '2026-05-18T02:00:00Z')
    names = scan_local_dir_names(tmp_path)
    assert sorted(names) == [
        '202605180100_000001_az',
        '202605180200_000002_dmc',
    ]


def test_scan_local_dir_names_skips_non_run_dirs(tmp_path):
    (tmp_path / 'artifacts').mkdir()
    (tmp_path / 'artifacts' / 'random_dir').mkdir()
    (tmp_path / 'artifacts' / 'README.md').write_text('x')
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    names = scan_local_dir_names(tmp_path)
    assert names == ['202605180100_000001_az']


def test_scan_local_dir_names_no_artifacts_dir(tmp_path):
    assert scan_local_dir_names(tmp_path) == []


# ---------------------------------------------------------------------------
# parse_remote_dir_names — same SSH stream re-parsed for dir names
# ---------------------------------------------------------------------------


def test_parse_remote_dir_names_extracts_names():
    text = (
        '===FILE artifacts/202605180100_000001_az/metadata.toml\n'
        'timestamp = "2026-05-18T01:00:00Z"\n'
        '===END\n'
        '===FILE artifacts/202605180200_000002_dmc/metadata.toml\n'
        'timestamp = "2026-05-18T02:00:00Z"\n'
        '===END\n'
    )
    assert parse_remote_dir_names(text) == [
        '202605180100_000001_az',
        '202605180200_000002_dmc',
    ]


def test_parse_remote_dir_names_skips_malformed_paths():
    text = (
        '===FILE artifacts/bogus_dir_name/metadata.toml\n'
        'timestamp = "2026-05-18T01:00:00Z"\n'
        '===END\n'
        '===FILE artifacts/202605180100_000001_az/metadata.toml\n'
        'timestamp = "2026-05-18T01:00:00Z"\n'
        '===END\n'
    )
    assert parse_remote_dir_names(text) == ['202605180100_000001_az']


def test_parse_remote_dir_names_empty_input():
    assert parse_remote_dir_names('') == []


# ---------------------------------------------------------------------------
# sync() — case-collide raises across union(local, remote)
# ---------------------------------------------------------------------------


def test_sync_raises_when_local_and_remote_collide(tmp_path):
    """macOS source has ``..._DMC_smoke`` (full name), Linux remote reports
    ``..._dmc_smoke`` with the SAME ts-prefix + NNN — pulling onto APFS
    would silently overwrite. ``make_run_dir`` only creates one side
    locally; the remote side is synthesised by the SSH runner stub."""
    make_run_dir(tmp_path, '202605180100', '000001', 'DMC_smoke', '2026-05-18T01:00:00Z')

    def ssh_runner(_cmd, **_kw):
        from tools.runs.tests._sync_fixtures import FakeResult

        # Remote dir name shares ts+NNN with local but differs in label case.
        blocks = (
            '===FILE artifacts/202605180100_000001_dmc_smoke/metadata.toml\n'
            'timestamp = "2026-05-18T03:00:00Z"\n'
            '===END\n'
        )
        return FakeResult(returncode=0, stdout=blocks)

    with pytest.raises(sync.CaseCollideError) as exc_info:
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=ssh_runner,
            dry_run=True,
        )
    msg = str(exc_info.value)
    assert 'DMC_smoke' in msg and 'dmc_smoke' in msg


def test_sync_raises_when_local_collides_with_remote_label_case_only(tmp_path):
    """Pure remote-side collision (one local dir, one remote dir with
    case-different label). Tests the union(local, remote) coverage of
    the pre-flight check without needing two on-disk dirs that APFS
    would itself collapse."""
    make_run_dir(tmp_path, '202605180100', '000001', 'AZ_smoke', '2026-05-18T01:00:00Z')

    def ssh_runner(_cmd, **_kw):
        from tools.runs.tests._sync_fixtures import FakeResult

        blocks = (
            '===FILE artifacts/202605180100_000001_az_smoke/metadata.toml\ntimestamp = "2026-05-18T02:00:00Z"\n===END\n'
        )
        return FakeResult(returncode=0, stdout=blocks)

    with pytest.raises(sync.CaseCollideError, match='AZ_smoke'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=ssh_runner,
            dry_run=True,
        )


def test_sync_lists_multiple_collisions_in_one_error(tmp_path):
    """Two independent collisions surfaced together so the user resolves
    in one pass."""
    make_run_dir(tmp_path, '202605180100', '000001', 'AZ', '2026-05-18T01:00:00Z')
    make_run_dir(tmp_path, '202605180300', '000003', 'DMC', '2026-05-18T03:00:00Z')

    def ssh_runner(_cmd, **_kw):
        from tools.runs.tests._sync_fixtures import FakeResult

        blocks = (
            '===FILE artifacts/202605180100_000001_az/metadata.toml\n'
            'timestamp = "2026-05-18T02:00:00Z"\n'
            '===END\n'
            '===FILE artifacts/202605180300_000003_dmc/metadata.toml\n'
            'timestamp = "2026-05-18T04:00:00Z"\n'
            '===END\n'
        )
        return FakeResult(returncode=0, stdout=blocks)

    with pytest.raises(sync.CaseCollideError) as exc_info:
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=ssh_runner,
            dry_run=True,
        )
    msg = str(exc_info.value)
    assert 'AZ' in msg and 'az' in msg
    assert 'DMC' in msg and 'dmc' in msg


def test_sync_no_collision_proceeds_normally(tmp_path):
    """Sanity: differently-cased dirs that DON'T collide (different
    label entirely) sync OK."""
    make_run_dir(tmp_path, '202605180100', '000001', 'az', '2026-05-18T01:00:00Z')
    cmd = sync.sync(
        direction='push',
        remote='u@h:/p/',
        root=tmp_path,
        ssh_runner=ssh_runner_returning({'000002': '2026-05-18T02:00:00Z'}),
        dry_run=True,
    )
    assert isinstance(cmd, list)
    assert cmd[0] == 'rsync'


def test_sync_case_collide_message_includes_advice(tmp_path):
    """Error message must guide user to manual rename."""
    make_run_dir(tmp_path, '202605180100', '000001', 'DMC', '2026-05-18T01:00:00Z')

    def ssh_runner(_cmd, **_kw):
        from tools.runs.tests._sync_fixtures import FakeResult

        return FakeResult(
            returncode=0,
            stdout=(
                '===FILE artifacts/202605180100_000001_dmc/metadata.toml\ntimestamp = "2026-05-18T02:00:00Z"\n===END\n'
            ),
        )

    with pytest.raises(sync.CaseCollideError, match='[Rr]ename'):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            ssh_runner=ssh_runner,
            dry_run=True,
        )


def test_sync_case_collide_raises_before_rsync_runs(tmp_path):
    """Collision must raise BEFORE the rsync subprocess fires (defence
    is pre-flight). Runner gets no calls."""
    captured: list[list[str]] = []

    def runner(cmd, **_kw):
        captured.append(list(cmd))
        from tools.runs.tests._sync_fixtures import FakeResult

        return FakeResult()

    make_run_dir(tmp_path, '202605180100', '000001', 'AZ', '2026-05-18T01:00:00Z')

    def ssh_runner(_cmd, **_kw):
        from tools.runs.tests._sync_fixtures import FakeResult

        return FakeResult(
            returncode=0,
            stdout=(
                '===FILE artifacts/202605180100_000001_az/metadata.toml\ntimestamp = "2026-05-18T02:00:00Z"\n===END\n'
            ),
        )

    with pytest.raises(sync.CaseCollideError):
        sync.sync(
            direction='push',
            remote='u@h:/p/',
            root=tmp_path,
            runner=runner,
            ssh_runner=ssh_runner,
        )
    assert captured == []  # rsync never invoked
