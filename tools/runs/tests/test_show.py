"""``tools.runs.show`` tests — clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§CLI show 细则 HIGH-1-C + §Schema CRIT-6-A +
§Malformed metadata 处理 HIGH-4-A.

Fixtures lay down ``artifacts/<ts>_<NNN>_<label>/{metadata.toml,
cfg_resolved.toml[, cfg_resolved_v<N>.toml]}`` directly — register /
complete were retired by the redesign; T-08 train.py is the only writer
in production.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs import schema
from tools.runs import show as show_cmd


def _write_run(
    repo_root: Path,
    *,
    nnn: str,
    label: str = 'probe',
    timestamp: str = '2026-05-18T03:55:21+00:00',
    status: str = 'done',
    wall_seconds: float = 84.3,
    exit_code: int = 0,
    notes: str = '',
    cfg_resolved_version: int = 1,
    cfg_files: dict[str, str] | None = None,
) -> Path:
    """Lay down one ``artifacts/<ts>_<nnn>_<label>/`` with metadata + cfgs.

    - ``timestamp`` is iso8601 UTC; dir-name 12-digit prefix derived from
      it (``YYYYMMDDhhmm``).
    - ``cfg_files`` maps filename (e.g. ``'cfg_resolved.toml'``,
      ``'cfg_resolved_v2.toml'``) → body. Defaults to a single
      ``cfg_resolved.toml`` with a minimal ``[meta]`` block.
    - Returns the created run dir.
    """
    ts_compact = timestamp[:16].replace('-', '').replace('T', '').replace(':', '')
    assert len(ts_compact) == 12, f'bad timestamp shape for dir prefix: {ts_compact}'

    run_dir = repo_root / 'artifacts' / f'{ts_compact}_{nnn}_{label}'
    run_dir.mkdir(parents=True)

    meta = schema.RunMetadata(
        run_id=nnn,
        timestamp=timestamp,
        cfg_file=f'configs/{label}.toml',
        cfg_resolved_version=cfg_resolved_version,
        git_commit='abc1234',
        host='test-host',
        status=status,
        artifacts_dir=f'artifacts/{ts_compact}_{nnn}_{label}',
        wall_seconds=wall_seconds,
        exit_code=exit_code,
        notes=notes,
    )
    (run_dir / 'metadata.toml').write_text(schema.dumps(meta), encoding='utf-8')

    if cfg_files is None:
        cfg_files = {'cfg_resolved.toml': f'[meta]\nparadigm = "az"\nrun_label = "{label}"\n'}
    for fname, body in cfg_files.items():
        (run_dir / fname).write_text(body, encoding='utf-8')

    return run_dir


# ---------------------------------------------------------------- NNN shorthand


class TestNNNShorthand:
    def test_full_six_digit(self, tmp_path):
        _write_run(tmp_path, nnn='000069')
        out = show_cmd.show_run(tmp_path, '000069')
        assert 'run_id: 000069' in out

    def test_two_digit_shorthand(self, tmp_path):
        """``69`` resolves to ``000069`` via zero-pad."""
        _write_run(tmp_path, nnn='000069')
        out = show_cmd.show_run(tmp_path, '69')
        assert 'run_id: 000069' in out

    def test_three_digit_shorthand(self, tmp_path):
        """``069`` resolves to ``000069``."""
        _write_run(tmp_path, nnn='000069')
        out = show_cmd.show_run(tmp_path, '069')
        assert 'run_id: 000069' in out

    def test_shorthand_equivalence(self, tmp_path):
        """``69`` / ``069`` / ``000069`` produce identical output."""
        _write_run(tmp_path, nnn='000069')
        out_2 = show_cmd.show_run(tmp_path, '69')
        out_3 = show_cmd.show_run(tmp_path, '069')
        out_6 = show_cmd.show_run(tmp_path, '000069')
        assert out_2 == out_3 == out_6

    def test_not_found_raises(self, tmp_path):
        """0 dir match → LookupError (bubbles up from resolver)."""
        _write_run(tmp_path, nnn='000069')
        with pytest.raises(LookupError, match='NNN not found'):
            show_cmd.show_run(tmp_path, '70')

    def test_multiple_match_raises(self, tmp_path):
        """≥2 dirs same NNN → LookupError listing candidates."""
        _write_run(tmp_path, nnn='000069', label='a', timestamp='2026-05-18T03:00:00+00:00')
        _write_run(tmp_path, nnn='000069', label='b', timestamp='2026-05-18T04:00:00+00:00')
        with pytest.raises(LookupError, match='multiple dirs match'):
            show_cmd.show_run(tmp_path, '69')

    def test_non_digit_raises(self, tmp_path):
        """``abc`` is not a digit string → ValueError from resolver."""
        with pytest.raises(ValueError, match='must be 1-6 digit string'):
            show_cmd.show_run(tmp_path, 'abc')

    def test_too_long_raises(self, tmp_path):
        """7-digit input rejected by resolver shape check."""
        with pytest.raises(ValueError, match='must be 1-6 digit string'):
            show_cmd.show_run(tmp_path, '1234567')


# ---------------------------------------------------------------- metadata output


class TestMetadataOutput:
    def test_all_eleven_fields_appear(self, tmp_path):
        """Every one of the 11 schema fields appears as a labeled line."""
        _write_run(
            tmp_path,
            nnn='000007',
            label='probe',
            timestamp='2026-05-18T03:55:21+00:00',
            status='done',
            wall_seconds=84.3,
            exit_code=0,
            notes='ran clean',
        )
        out = show_cmd.show_run(tmp_path, '7')
        for field in (
            'run_id',
            'timestamp',
            'cfg_file',
            'cfg_resolved_version',
            'git_commit',
            'host',
            'status',
            'artifacts_dir',
            'wall_seconds',
            'exit_code',
            'notes',
        ):
            assert f'{field}:' in out, f'missing field {field!r} in output:\n{out}'

    def test_field_values_rendered(self, tmp_path):
        """Specific field values appear in output."""
        _write_run(
            tmp_path,
            nnn='000007',
            label='probe',
            timestamp='2026-05-18T03:55:21+00:00',
            status='running',
            wall_seconds=12.5,
            exit_code=1,
            notes='still going',
        )
        out = show_cmd.show_run(tmp_path, '7')
        assert 'run_id: 000007' in out
        assert 'timestamp: 2026-05-18T03:55:21+00:00' in out
        assert 'status: running' in out
        assert 'wall_seconds: 12.5' in out
        assert 'exit_code: 1' in out
        assert 'notes: still going' in out

    def test_metadata_header_present(self, tmp_path):
        _write_run(tmp_path, nnn='000001')
        out = show_cmd.show_run(tmp_path, '1')
        assert '=== metadata ===' in out


# ---------------------------------------------------------------- cfg_resolved versions


class TestCfgResolvedVersions:
    def test_single_v1_marked_current(self, tmp_path):
        """Only ``cfg_resolved.toml`` present → v1 marked ``(current)``."""
        _write_run(tmp_path, nnn='000001')
        out = show_cmd.show_run(tmp_path, '1')
        assert '=== cfg_resolved_v1 (current) (cfg_resolved.toml) ===' in out

    def test_multi_version_all_listed(self, tmp_path):
        """v1 + v2 + v3 all listed; only v3 marked ``(current)``."""
        _write_run(
            tmp_path,
            nnn='000069',
            cfg_resolved_version=3,
            cfg_files={
                'cfg_resolved.toml': '[meta]\nparadigm = "az"\nrun_label = "p"\n',
                'cfg_resolved_v2.toml': '[meta]\nparadigm = "az"\nrun_label = "p"\nnote = "second"\n',
                'cfg_resolved_v3.toml': '[meta]\nparadigm = "dmc"\nrun_label = "p"\nnote = "third"\n',
            },
        )
        out = show_cmd.show_run(tmp_path, '69')
        # All three versions appear.
        assert '=== cfg_resolved_v1' in out
        assert '=== cfg_resolved_v2' in out
        assert '=== cfg_resolved_v3' in out
        # Only v3 marked current.
        assert '=== cfg_resolved_v3 (current) (cfg_resolved_v3.toml) ===' in out
        # v1, v2 do NOT carry the (current) marker.
        assert '=== cfg_resolved_v1 (current)' not in out
        assert '=== cfg_resolved_v2 (current)' not in out

    def test_versions_in_ascending_order(self, tmp_path):
        """Sections emitted v1 → v2 → v3 regardless of dir iteration order."""
        _write_run(
            tmp_path,
            nnn='000069',
            cfg_resolved_version=3,
            cfg_files={
                'cfg_resolved.toml': '[meta]\nparadigm = "az"\nrun_label = "p"\n',
                'cfg_resolved_v2.toml': '[meta]\nparadigm = "az"\nrun_label = "p"\n',
                'cfg_resolved_v3.toml': '[meta]\nparadigm = "dmc"\nrun_label = "p"\n',
            },
        )
        out = show_cmd.show_run(tmp_path, '69')
        idx_v1 = out.index('=== cfg_resolved_v1')
        idx_v2 = out.index('=== cfg_resolved_v2')
        idx_v3 = out.index('=== cfg_resolved_v3')
        assert idx_v1 < idx_v2 < idx_v3

    def test_v1_v2_only(self, tmp_path):
        """v1 + v2 → v2 marked current."""
        _write_run(
            tmp_path,
            nnn='000042',
            cfg_resolved_version=2,
            cfg_files={
                'cfg_resolved.toml': '[meta]\nparadigm = "az"\nrun_label = "p"\n',
                'cfg_resolved_v2.toml': '[meta]\nparadigm = "dmc"\nrun_label = "p"\n',
            },
        )
        out = show_cmd.show_run(tmp_path, '42')
        assert '=== cfg_resolved_v2 (current) (cfg_resolved_v2.toml) ===' in out
        assert '=== cfg_resolved_v1 (current)' not in out

    def test_cfg_body_included(self, tmp_path):
        """Raw cfg TOML body is included in each section."""
        body = '[meta]\nparadigm = "dmc"\nrun_label = "smoke"\ncustom_key = "marker_xyz"\n'
        _write_run(tmp_path, nnn='000001', cfg_files={'cfg_resolved.toml': body})
        out = show_cmd.show_run(tmp_path, '1')
        assert 'paradigm = "dmc"' in out
        assert 'marker_xyz' in out

    def test_internal_lister_versions(self, tmp_path):
        """Unit-level: _list_cfg_resolved_versions returns sorted [(N, Path), ...]."""
        run_dir = _write_run(
            tmp_path,
            nnn='000001',
            cfg_resolved_version=3,
            cfg_files={
                'cfg_resolved.toml': 'x = 1\n',
                'cfg_resolved_v2.toml': 'x = 2\n',
                'cfg_resolved_v3.toml': 'x = 3\n',
            },
        )
        versions = show_cmd._list_cfg_resolved_versions(run_dir)
        assert [v for v, _ in versions] == [1, 2, 3]
        # Confirm path basenames match.
        assert versions[0][1].name == 'cfg_resolved.toml'
        assert versions[1][1].name == 'cfg_resolved_v2.toml'
        assert versions[2][1].name == 'cfg_resolved_v3.toml'

    def test_internal_lister_skips_unrelated_files(self, tmp_path):
        """Files not matching the cfg_resolved naming pattern are ignored."""
        run_dir = _write_run(
            tmp_path,
            nnn='000001',
            cfg_files={
                'cfg_resolved.toml': 'x = 1\n',
                'cfg_leaf.toml': 'x = 2\n',  # peer leaf cfg — must be skipped
                'cfg_resolved_v2.toml.bak': 'x = 3\n',  # backup — must be skipped
                'random_other.txt': 'noise',
            },
        )
        versions = show_cmd._list_cfg_resolved_versions(run_dir)
        assert [v for v, _ in versions] == [1]

    def test_empty_dir_renders_warning_section(self, tmp_path):
        """Defensive: artifacts dir exists but no cfg_resolved*.toml at all.

        Spec doesn't expect this from production train.py (always writes v1),
        but recover / hand-crafted dirs may produce it — we emit a notice
        section rather than silently dropping it.
        """
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_a'
        run_dir.mkdir(parents=True)
        meta = schema.RunMetadata(
            run_id='000001',
            timestamp='2026-05-18T03:00:00+00:00',
            cfg_file='configs/a.toml',
            cfg_resolved_version=1,
            git_commit='abc1234',
            host='test-host',
            status='unknown',
            artifacts_dir='artifacts/202605180300_000001_a',
            wall_seconds=0.0,
            exit_code=0,
            notes='',
        )
        (run_dir / 'metadata.toml').write_text(schema.dumps(meta), encoding='utf-8')

        out = show_cmd.show_run(tmp_path, '1')
        # Metadata still printed.
        assert 'run_id: 000001' in out
        # Notice section appears (not a (current) header).
        assert '=== cfg_resolved ===' in out
        assert 'no cfg_resolved' in out


# ---------------------------------------------------------------- malformed handling


class TestMalformedRaises:
    """Per spec §HIGH-4-A: ``show`` on a single NNN **raises**, unlike ``list``
    which skips. Failing loud is correct for a single-target query — silent
    success on a corrupt file would hide real damage."""

    def test_malformed_toml_raises(self, tmp_path):
        """``show_run`` propagates parse failure (does NOT skip)."""
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_bad'
        run_dir.mkdir(parents=True)
        (run_dir / 'metadata.toml').write_text('not = a [ valid toml ]] file', encoding='utf-8')

        with pytest.raises(ValueError):
            show_cmd.show_run(tmp_path, '1')

    def test_schema_violation_raises(self, tmp_path):
        """metadata.toml parses but is missing fields → ValueError raised."""
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_bad'
        run_dir.mkdir(parents=True)
        (run_dir / 'metadata.toml').write_text('run_id = "000001"\n', encoding='utf-8')

        with pytest.raises(ValueError, match='missing required keys'):
            show_cmd.show_run(tmp_path, '1')

    def test_metadata_file_missing_raises(self, tmp_path):
        """Dir exists but no metadata.toml → OSError (FileNotFoundError)."""
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_bare'
        run_dir.mkdir(parents=True)
        # NB: also create a cfg_resolved so the dir is recognizably a run dir,
        # but no metadata.toml. resolver matches dir, schema.load_file fails.
        (run_dir / 'cfg_resolved.toml').write_text('[meta]\n', encoding='utf-8')

        with pytest.raises(OSError):
            show_cmd.show_run(tmp_path, '1')

    def test_main_malformed_returns_exit_2(self, tmp_path, capsys):
        """CLI: malformed metadata → stderr + exit 2 (not raise)."""
        run_dir = tmp_path / 'artifacts' / '202605180300_000001_bad'
        run_dir.mkdir(parents=True)
        (run_dir / 'metadata.toml').write_text('garbage', encoding='utf-8')

        rc = show_cmd.main(['1', '--root', str(tmp_path)])
        assert rc == 2
        err = capsys.readouterr().err
        assert 'tools.runs.show:' in err

    def test_main_not_found_returns_exit_2(self, tmp_path, capsys):
        """CLI: NNN not found → stderr + exit 2."""
        rc = show_cmd.main(['999', '--root', str(tmp_path)])
        assert rc == 2
        err = capsys.readouterr().err
        assert 'tools.runs.show:' in err
        assert 'NNN not found' in err

    def test_main_multi_match_returns_exit_2(self, tmp_path, capsys):
        """CLI: ≥2 dirs match → stderr + exit 2."""
        _write_run(tmp_path, nnn='000069', label='a', timestamp='2026-05-18T03:00:00+00:00')
        _write_run(tmp_path, nnn='000069', label='b', timestamp='2026-05-18T04:00:00+00:00')
        rc = show_cmd.main(['69', '--root', str(tmp_path)])
        assert rc == 2
        err = capsys.readouterr().err
        assert 'multiple dirs match' in err

    def test_main_invalid_nnn_returns_exit_2(self, tmp_path, capsys):
        """CLI: non-digit NNN → ValueError caught → exit 2."""
        rc = show_cmd.main(['abc', '--root', str(tmp_path)])
        assert rc == 2
        err = capsys.readouterr().err
        assert 'tools.runs.show:' in err


# ---------------------------------------------------------------- CLI integration


class TestCLI:
    def test_cli_basic_prints_metadata(self, tmp_path, capsys):
        _write_run(tmp_path, nnn='000007', label='probe', status='done', wall_seconds=42.0)
        rc = show_cmd.main(['7', '--root', str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert 'run_id: 000007' in out
        assert 'status: done' in out
        assert 'wall_seconds: 42.0' in out

    def test_cli_prints_cfg_resolved(self, tmp_path, capsys):
        body = '[meta]\nparadigm = "dmc"\nrun_label = "smoke"\n'
        _write_run(tmp_path, nnn='000007', cfg_files={'cfg_resolved.toml': body})
        rc = show_cmd.main(['7', '--root', str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert '=== cfg_resolved_v1 (current)' in out
        assert 'paradigm = "dmc"' in out

    def test_subprocess_invocation(self, tmp_path):
        """End-to-end: spawn the CLI via ``python -m`` and parse stdout."""
        _write_run(tmp_path, nnn='000007', label='probe')
        repo_root = Path(__file__).resolve().parents[3]
        result = subprocess.run(
            [sys.executable, '-m', 'tools.runs.show', '7', '--root', str(tmp_path)],
            capture_output=True,
            text=True,
            cwd=repo_root,
        )
        assert result.returncode == 0, result.stderr
        assert 'run_id: 000007' in result.stdout
        assert '=== cfg_resolved_v1 (current)' in result.stdout
