"""``tools.runs.list`` tests — clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§CLI list 细则 HIGH-1-B + §Malformed metadata 处理 HIGH-4-A.

Fixtures lay down ``artifacts/<ts>_<NNN>_<label>/{metadata.toml,
cfg_resolved.toml[, cfg_resolved_v2.toml]}`` directly (no register
helper — register/complete were retired by the redesign; T-08 train.py
is the only writer of these files in production).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs import list as list_cmd
from tools.runs import schema


def _write_metadata(
    repo_root: Path,
    *,
    nnn: str,
    label: str,
    timestamp: str,
    status: str = 'done',
    wall_seconds: float = 0.0,
    exit_code: int = 0,
    notes: str = '',
    paradigm: str | None = 'az',
    cfg_resolved_v2_paradigm: str | None = None,
) -> Path:
    """Lay down one ``artifacts/<ts>_<nnn>_<label>/`` with metadata + cfg.

    - ``timestamp`` is iso8601 UTC; the dir name's 12-digit prefix is
      derived from it (``YYYYMMDDhhmm``).
    - ``paradigm`` writes a ``cfg_resolved.toml`` with that ``meta.paradigm``;
      pass ``None`` to omit the cfg_resolved file entirely (tests the
      paradigm='?' fallback path).
    - ``cfg_resolved_v2_paradigm`` writes a ``cfg_resolved_v2.toml`` to
      simulate the resume path; list_runs must read the v2 paradigm
      (highest version = truth per spec §Resume 语义).

    Returns the created run dir path.
    """
    # Build dir-name prefix from timestamp: YYYY-MM-DDTHH:MM:SS+... → YYYYMMDDHHMM
    ts_compact = timestamp[:16].replace('-', '').replace('T', '').replace(':', '')
    assert len(ts_compact) == 12, f'bad timestamp shape for dir prefix: {ts_compact}'

    run_dir = repo_root / 'artifacts' / f'{ts_compact}_{nnn}_{label}'
    run_dir.mkdir(parents=True)

    meta = schema.RunMetadata(
        run_id=nnn,
        timestamp=timestamp,
        cfg_file=f'configs/{label}.toml',
        cfg_resolved_version=1 if cfg_resolved_v2_paradigm is None else 2,
        git_commit='abc1234',
        host='test-host',
        status=status,
        artifacts_dir=f'artifacts/{ts_compact}_{nnn}_{label}',
        wall_seconds=wall_seconds,
        exit_code=exit_code,
        notes=notes,
    )
    (run_dir / 'metadata.toml').write_text(schema.dumps(meta), encoding='utf-8')

    if paradigm is not None:
        (run_dir / 'cfg_resolved.toml').write_text(
            f'[meta]\nparadigm = "{paradigm}"\nrun_label = "{label}"\n',
            encoding='utf-8',
        )
    if cfg_resolved_v2_paradigm is not None:
        (run_dir / 'cfg_resolved_v2.toml').write_text(
            f'[meta]\nparadigm = "{cfg_resolved_v2_paradigm}"\nrun_label = "{label}"\n',
            encoding='utf-8',
        )
    return run_dir


# ---------------------------------------------------------------- empty scans


class TestEmptyScan:
    def test_artifacts_missing(self, tmp_path):
        """No ``artifacts/`` dir at all → 0 rows, no error."""
        rows = list_cmd.list_runs(tmp_path)
        assert rows == []

    def test_artifacts_empty(self, tmp_path):
        (tmp_path / 'artifacts').mkdir()
        rows = list_cmd.list_runs(tmp_path)
        assert rows == []

    def test_cli_empty_prints_hint(self, tmp_path, capsys):
        rc = list_cmd.main(['--root', str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'no runs found' in out

    def test_skips_non_run_dirs(self, tmp_path):
        """Pre-redesign legacy dirs (no 12-digit prefix) silently skip."""
        (tmp_path / 'artifacts').mkdir()
        (tmp_path / 'artifacts' / 'r001_old').mkdir()  # legacy
        (tmp_path / 'artifacts' / 'pre_redesign_xxx').mkdir()  # legacy
        (tmp_path / 'artifacts' / 'runs').mkdir()  # old index dir
        # Plus a file at artifacts/.run_id_lock — not a dir, must skip.
        (tmp_path / 'artifacts' / '.run_id_lock').write_text('')
        rows = list_cmd.list_runs(tmp_path)
        assert rows == []


# ---------------------------------------------------------------- basic scan


class TestBasicScan:
    def test_three_runs_default_sort_desc(self, tmp_path):
        """3 runs with distinct timestamps → 3 rows sorted timestamp desc."""
        _write_metadata(tmp_path, nnn='000001', label='r1', timestamp='2026-05-18T03:00:00+00:00', status='done')
        _write_metadata(tmp_path, nnn='000002', label='r2', timestamp='2026-05-18T04:00:00+00:00', status='running')
        _write_metadata(tmp_path, nnn='000003', label='r3', timestamp='2026-05-18T05:00:00+00:00', status='failed')
        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 3
        # Newest first.
        assert rows[0].nnn == '000003'
        assert rows[1].nnn == '000002'
        assert rows[2].nnn == '000001'

    def test_tie_break_nnn_desc(self, tmp_path):
        """Same timestamp → tie-break by NNN desc (newer NNN first)."""
        ts = '2026-05-18T03:00:00+00:00'
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp=ts)
        _write_metadata(tmp_path, nnn='000002', label='b', timestamp=ts)
        rows = list_cmd.list_runs(tmp_path)
        assert [r.nnn for r in rows] == ['000002', '000001']

    def test_row_fields(self, tmp_path):
        """Row carries nnn, status, paradigm, timestamp, wall, label, notes."""
        _write_metadata(
            tmp_path,
            nnn='000007',
            label='probe',
            timestamp='2026-05-18T03:00:00+00:00',
            status='done',
            wall_seconds=84.3,
            notes='ran clean',
            paradigm='dmc',
        )
        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 1
        r = rows[0]
        assert r.nnn == '000007'
        assert r.status == 'done'
        assert r.paradigm == 'dmc'
        assert r.timestamp == '2026-05-18T03:00:00+00:00'
        assert r.wall_seconds == pytest.approx(84.3)
        assert r.run_label == 'probe'
        assert r.notes == 'ran clean'


# ---------------------------------------------------------------- filters


class TestFilters:
    def test_status_filter_keeps_only_match(self, tmp_path):
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', status='done')
        _write_metadata(tmp_path, nnn='000002', label='b', timestamp='2026-05-18T04:00:00+00:00', status='running')
        _write_metadata(tmp_path, nnn='000003', label='c', timestamp='2026-05-18T05:00:00+00:00', status='failed')
        rows = list_cmd.list_runs(tmp_path, status_filter='done')
        assert len(rows) == 1
        assert rows[0].nnn == '000001'

    def test_paradigm_filter_keeps_only_match(self, tmp_path):
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', paradigm='az')
        _write_metadata(tmp_path, nnn='000002', label='b', timestamp='2026-05-18T04:00:00+00:00', paradigm='dmc')
        _write_metadata(tmp_path, nnn='000003', label='c', timestamp='2026-05-18T05:00:00+00:00', paradigm='ppo')
        rows = list_cmd.list_runs(tmp_path, paradigm_filter='dmc')
        assert len(rows) == 1
        assert rows[0].nnn == '000002'
        assert rows[0].paradigm == 'dmc'

    def test_status_and_paradigm_both(self, tmp_path):
        _write_metadata(
            tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', status='running', paradigm='az'
        )
        _write_metadata(
            tmp_path, nnn='000002', label='b', timestamp='2026-05-18T04:00:00+00:00', status='running', paradigm='dmc'
        )
        _write_metadata(
            tmp_path, nnn='000003', label='c', timestamp='2026-05-18T05:00:00+00:00', status='done', paradigm='az'
        )
        rows = list_cmd.list_runs(tmp_path, status_filter='running', paradigm_filter='az')
        assert len(rows) == 1
        assert rows[0].nnn == '000001'

    def test_invalid_status_filter_raises(self, tmp_path):
        with pytest.raises(ValueError, match='status_filter'):
            list_cmd.list_runs(tmp_path, status_filter='pending')

    def test_invalid_paradigm_filter_raises(self, tmp_path):
        with pytest.raises(ValueError, match='paradigm_filter'):
            list_cmd.list_runs(tmp_path, paradigm_filter='reinforce')

    def test_argparse_rejects_unknown_status(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            list_cmd.main(['--root', str(tmp_path), '--status', 'bogus'])
        err = capsys.readouterr().err
        assert 'bogus' in err or 'invalid choice' in err

    def test_argparse_rejects_unknown_paradigm(self, tmp_path, capsys):
        with pytest.raises(SystemExit):
            list_cmd.main(['--root', str(tmp_path), '--paradigm', 'bogus'])
        err = capsys.readouterr().err
        assert 'bogus' in err or 'invalid choice' in err


# ---------------------------------------------------------------- malformed handling


class TestMalformedHandling:
    def test_skip_malformed_keep_rest(self, tmp_path, capsys):
        """3 valid + 1 broken → list 3 rows + stderr 'skipping <NNN>: malformed metadata'."""
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00')
        _write_metadata(tmp_path, nnn='000002', label='b', timestamp='2026-05-18T04:00:00+00:00')
        _write_metadata(tmp_path, nnn='000003', label='c', timestamp='2026-05-18T05:00:00+00:00')
        # Hand-craft the 4th dir with corrupt metadata.toml.
        broken = tmp_path / 'artifacts' / '202605180600_000004_broken'
        broken.mkdir()
        (broken / 'metadata.toml').write_text('not = a [ valid toml ]] file', encoding='utf-8')

        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 3
        assert {r.nnn for r in rows} == {'000001', '000002', '000003'}
        err = capsys.readouterr().err
        assert 'skipping 000004' in err
        assert 'malformed metadata' in err

    def test_skip_schema_violation(self, tmp_path, capsys):
        """metadata.toml parses but fails schema validate → skip + warn."""
        _write_metadata(tmp_path, nnn='000001', label='ok', timestamp='2026-05-18T03:00:00+00:00')
        bad = tmp_path / 'artifacts' / '202605180400_000002_bad'
        bad.mkdir()
        # Missing required keys → from_dict raises ValueError ('missing required keys').
        (bad / 'metadata.toml').write_text('run_id = "000002"\n', encoding='utf-8')

        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].nnn == '000001'
        err = capsys.readouterr().err
        assert 'skipping 000002' in err
        assert 'malformed metadata' in err

    def test_missing_metadata_silent_skip(self, tmp_path, capsys):
        """Run dir without metadata.toml → silent skip (not 'malformed').

        Per spec §Malformed metadata 处理 HIGH-4-A distinction: missing is recover-eligible (T-15
        recover command's job), not a corruption warning.
        """
        _write_metadata(tmp_path, nnn='000001', label='ok', timestamp='2026-05-18T03:00:00+00:00')
        bare = tmp_path / 'artifacts' / '202605180400_000002_bare'
        bare.mkdir()  # no metadata.toml inside

        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 1
        err = capsys.readouterr().err
        # No 'skipping' warn — missing is intentional silent-skip.
        assert 'skipping' not in err

    def test_unparseable_dir_name_uses_question_mark(self, tmp_path, capsys):
        """Hand-crafted dir whose name matches RUN_DIR_RE but metadata
        broken → warning uses NNN extracted from dir name. (No coverage
        for the '?' fallback in _scan_one's nnn_from_dir because
        list_runs filters non-matching dirs upstream — this test
        documents that the regex-extracted NNN is what reaches stderr.)
        """
        broken = tmp_path / 'artifacts' / '202605180600_000007_broken'
        broken.mkdir(parents=True)
        (broken / 'metadata.toml').write_text('garbage', encoding='utf-8')

        rows = list_cmd.list_runs(tmp_path)
        assert rows == []
        err = capsys.readouterr().err
        assert 'skipping 000007' in err


# ---------------------------------------------------------------- paradigm derivation


class TestParadigmDerivation:
    def test_reads_cfg_resolved_meta_paradigm(self, tmp_path):
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', paradigm='dmc')
        rows = list_cmd.list_runs(tmp_path)
        assert rows[0].paradigm == 'dmc'

    def test_resume_uses_highest_version(self, tmp_path):
        """cfg_resolved.toml says 'az', cfg_resolved_v2.toml says 'dmc'
        (post-resume) → list shows 'dmc' (highest version = truth per
        spec §Resume 语义)."""
        _write_metadata(
            tmp_path,
            nnn='000001',
            label='a',
            timestamp='2026-05-18T03:00:00+00:00',
            paradigm='az',
            cfg_resolved_v2_paradigm='dmc',
        )
        rows = list_cmd.list_runs(tmp_path)
        assert rows[0].paradigm == 'dmc'

    def test_no_cfg_resolved_falls_back_to_question_mark(self, tmp_path):
        """metadata.toml exists but no cfg_resolved*.toml → paradigm = '?'."""
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', paradigm=None)
        rows = list_cmd.list_runs(tmp_path)
        assert rows[0].paradigm == '?'

    def test_cfg_resolved_missing_paradigm_field_falls_back(self, tmp_path):
        """cfg_resolved.toml exists but lacks meta.paradigm → '?'."""
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', paradigm=None)
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_a'
        (run_dir / 'cfg_resolved.toml').write_text('[meta]\nrun_label = "a"\n', encoding='utf-8')
        rows = list_cmd.list_runs(tmp_path)
        assert rows[0].paradigm == '?'

    def test_cfg_resolved_broken_falls_back(self, tmp_path):
        """Broken cfg_resolved.toml doesn't kill the row — paradigm = '?'."""
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', paradigm=None)
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_a'
        (run_dir / 'cfg_resolved.toml').write_text('not = a [ valid toml ]]', encoding='utf-8')
        rows = list_cmd.list_runs(tmp_path)
        assert len(rows) == 1
        assert rows[0].paradigm == '?'

    def test_paradigm_filter_works_with_v2(self, tmp_path):
        """Filter --paradigm dmc finds runs where v2 paradigm is dmc."""
        _write_metadata(
            tmp_path,
            nnn='000001',
            label='a',
            timestamp='2026-05-18T03:00:00+00:00',
            paradigm='az',
            cfg_resolved_v2_paradigm='dmc',
        )
        _write_metadata(
            tmp_path,
            nnn='000002',
            label='b',
            timestamp='2026-05-18T04:00:00+00:00',
            paradigm='az',
        )
        rows = list_cmd.list_runs(tmp_path, paradigm_filter='dmc')
        assert len(rows) == 1
        assert rows[0].nnn == '000001'


# ---------------------------------------------------------------- output format


class TestOutputFormat:
    def test_table_has_seven_columns(self, tmp_path):
        _write_metadata(
            tmp_path,
            nnn='000001',
            label='probe',
            timestamp='2026-05-18T03:00:00+00:00',
            status='done',
            wall_seconds=84.0,
            notes='hello',
        )
        rows = list_cmd.list_runs(tmp_path)
        table = list_cmd.render_table(rows)
        first_line = table.splitlines()[0]
        # Headers split by whitespace; expect exactly 7 column labels.
        for hdr in ('NNN', 'status', 'paradigm', 'started', 'wall', 'run_label', 'notes'):
            assert hdr in first_line

    def test_started_is_date_only(self, tmp_path):
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:55:21+00:00')
        table = list_cmd.render_table(list_cmd.list_runs(tmp_path))
        assert '2026-05-18' in table
        # No 'T03:55' or similar leaking from the full timestamp.
        assert 'T03:55' not in table

    @pytest.mark.parametrize(
        'seconds,expected',
        [
            (0, '-'),
            (1, '1s'),
            (59, '59s'),
            (60, '1m0s'),
            (84, '1m24s'),
            (3599, '59m59s'),
            (3600, '1h0m'),
            (7200, '2h0m'),
        ],
    )
    def test_wall_format(self, seconds, expected):
        assert list_cmd._format_wall(float(seconds)) == expected

    def test_render_truncates_long_notes(self, tmp_path):
        long = 'a' * 200
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', notes=long)
        table = list_cmd.render_table(list_cmd.list_runs(tmp_path))
        # Should not contain the full 200-char note (truncated to ~60).
        assert long not in table

    def test_render_notes_first_line_only(self, tmp_path):
        notes_text = 'first line\nshould-not-appear-line-2'
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', notes=notes_text)
        table = list_cmd.render_table(list_cmd.list_runs(tmp_path))
        assert 'first line' in table
        assert 'should-not-appear-line-2' not in table


# ---------------------------------------------------------------- CLI integration


class TestCLI:
    def test_cli_prints_table(self, tmp_path, capsys):
        _write_metadata(tmp_path, nnn='000001', label='probe', timestamp='2026-05-18T03:00:00+00:00', status='done')
        rc = list_cmd.main(['--root', str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert '000001' in out
        assert 'probe' in out
        assert 'done' in out

    def test_cli_status_filter(self, tmp_path, capsys):
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', status='running')
        _write_metadata(tmp_path, nnn='000002', label='b', timestamp='2026-05-18T04:00:00+00:00', status='done')
        rc = list_cmd.main(['--root', str(tmp_path), '--status', 'done'])
        assert rc == 0
        out = capsys.readouterr().out
        assert '000002' in out
        assert '000001' not in out

    def test_cli_paradigm_filter(self, tmp_path, capsys):
        _write_metadata(tmp_path, nnn='000001', label='a', timestamp='2026-05-18T03:00:00+00:00', paradigm='az')
        _write_metadata(tmp_path, nnn='000002', label='b', timestamp='2026-05-18T04:00:00+00:00', paradigm='dmc')
        rc = list_cmd.main(['--root', str(tmp_path), '--paradigm', 'dmc'])
        assert rc == 0
        out = capsys.readouterr().out
        assert '000002' in out
        assert '000001' not in out

    def test_subprocess_invocation(self, tmp_path):
        """End-to-end: spawn the CLI via ``python -m`` and parse the table."""
        _write_metadata(tmp_path, nnn='000001', label='probe', timestamp='2026-05-18T03:00:00+00:00', status='done')
        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, '-m', 'tools.runs.list', '--root', str(tmp_path), '--status', 'done'],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        assert result.returncode == 0, result.stderr
        assert '000001' in result.stdout
        assert 'probe' in result.stdout
