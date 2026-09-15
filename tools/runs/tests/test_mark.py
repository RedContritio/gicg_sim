"""Tests for ``tools.runs.mark`` (T-16 clean-slate redesign).

Covers spec §CLI mark 细则 HIGH-1-D + HIGH-6-A +
§Status 状态机 strict transitions + §metadata 写.

Spec contracts under test:

- NNN shorthand (1-6 digit) resolves to unique ``artifacts/`` dir via
  R7 :func:`resolve_nnn_to_dir`. 0 / ≥2 match → LookupError.
- Transition table: ``{running, unknown} → {done, failed, killed}`` OK;
  terminal-state sources (done / failed / killed) reject every target.
- ``--notes`` body passes through :func:`schema.dumps` TOML escape:
  raw ``\\n`` / control chars → ``\\\\n`` etc; TOML injection
  (``]\\n[other_section]``) gets escaped, not interpreted as new table.
- ``--notes`` omitted → existing notes preserved (round-trip identity).
- ``schema.load_file`` round-trips the escaped notes back to the
  original raw text on read.
- CLI exit codes: 0 success, 2 on lookup / transition / IO failure.

Test fixtures lay down ``artifacts/<ts>_<NNN>_<label>/metadata.toml``
directly (no register / complete — the legacy CLIs were retired by the
redesign; T-08 train.py is the only production metadata writer).
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs import mark as mark_cmd
from tools.runs import schema


# --- Fixtures ----------------------------------------------------------------


def _write_run(
    repo_root: Path,
    *,
    nnn: str,
    label: str = 'probe',
    timestamp: str = '2026-05-18T03:55:21+00:00',
    status: str = 'running',
    notes: str = '',
) -> Path:
    """Lay down one ``artifacts/<ts>_<nnn>_<label>/metadata.toml`` for tests.

    Returns the created run dir. The dir-name 12-digit prefix derives
    from ``timestamp[:16]`` (YYYYMMDDhhmm), matching the resolver regex.
    """
    ts_compact = timestamp[:16].replace('-', '').replace('T', '').replace(':', '')
    assert len(ts_compact) == 12, f'bad timestamp shape for dir prefix: {ts_compact}'

    run_dir = repo_root / 'artifacts' / f'{ts_compact}_{nnn}_{label}'
    run_dir.mkdir(parents=True)

    meta = schema.RunMetadata(
        run_id=nnn,
        timestamp=timestamp,
        cfg_file=f'configs/{label}.toml',
        cfg_resolved_version=1,
        git_commit='abc1234',
        host='test-host',
        status=status,
        artifacts_dir=f'artifacts/{ts_compact}_{nnn}_{label}',
        wall_seconds=0.0,
        exit_code=0,
        notes=notes,
    )
    (run_dir / 'metadata.toml').write_text(schema.dumps(meta), encoding='utf-8')
    return run_dir


def _read_meta(run_dir: Path) -> schema.RunMetadata:
    return schema.load_file(run_dir / 'metadata.toml')


# --- NNN lookup (R7 via resolve_nnn_to_dir) ----------------------------------


class TestNNNLookup:
    def test_full_six_digit(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000069', status='running')
        mark_cmd.mark_run(tmp_path, '000069', 'done', None)
        assert _read_meta(tmp_path / 'artifacts' / '202605180355_000069_probe').status == 'done'

    def test_two_digit_shorthand(self, tmp_path: Path) -> None:
        """``69`` resolves to ``000069`` via zero-pad (R7)."""
        run_dir = _write_run(tmp_path, nnn='000069', status='running')
        mark_cmd.mark_run(tmp_path, '69', 'done', None)
        assert _read_meta(run_dir).status == 'done'

    def test_three_digit_shorthand_equivalence(self, tmp_path: Path) -> None:
        """``069`` and ``000069`` mark the same run."""
        run_dir = _write_run(tmp_path, nnn='000069', status='running')
        mark_cmd.mark_run(tmp_path, '069', 'killed', None)
        assert _read_meta(run_dir).status == 'killed'

    def test_not_found_raises(self, tmp_path: Path) -> None:
        """0 dir match → LookupError (bubbles from resolver)."""
        _write_run(tmp_path, nnn='000069', status='running')
        with pytest.raises(LookupError, match='NNN not found'):
            mark_cmd.mark_run(tmp_path, '70', 'done', None)

    def test_multiple_match_raises(self, tmp_path: Path) -> None:
        """≥2 dirs same NNN → LookupError listing candidates."""
        _write_run(tmp_path, nnn='000069', label='a', timestamp='2026-05-18T03:00:00+00:00', status='running')
        _write_run(tmp_path, nnn='000069', label='b', timestamp='2026-05-18T04:00:00+00:00', status='running')
        with pytest.raises(LookupError, match='multiple dirs match'):
            mark_cmd.mark_run(tmp_path, '69', 'done', None)

    def test_non_digit_raises(self, tmp_path: Path) -> None:
        """``abc`` is not a digit string → ValueError from resolver."""
        with pytest.raises(ValueError, match='must be 1-6 digit string'):
            mark_cmd.mark_run(tmp_path, 'abc', 'done', None)


# --- Transition validation (spec strict §Status 状态机) ----------


class TestTransitions:
    def test_running_to_done(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000001', status='running')
        mark_cmd.mark_run(tmp_path, '1', 'done', None)
        assert _read_meta(run_dir).status == 'done'

    def test_running_to_failed(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000002', status='running')
        mark_cmd.mark_run(tmp_path, '2', 'failed', None)
        assert _read_meta(run_dir).status == 'failed'

    def test_running_to_killed(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000003', status='running')
        mark_cmd.mark_run(tmp_path, '3', 'killed', None)
        assert _read_meta(run_dir).status == 'killed'

    def test_unknown_to_done(self, tmp_path: Path) -> None:
        """``unknown`` (recover-rebuilt) → terminal allowed (spec §Status 状态机)."""
        run_dir = _write_run(tmp_path, nnn='000004', status='unknown')
        mark_cmd.mark_run(tmp_path, '4', 'done', None)
        assert _read_meta(run_dir).status == 'done'

    def test_unknown_to_failed(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000005', status='unknown')
        mark_cmd.mark_run(tmp_path, '5', 'failed', None)
        assert _read_meta(run_dir).status == 'failed'

    def test_unknown_to_killed(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000006', status='unknown')
        mark_cmd.mark_run(tmp_path, '6', 'killed', None)
        assert _read_meta(run_dir).status == 'killed'

    def test_done_to_done_rejects(self, tmp_path: Path) -> None:
        """Terminal-state mark is the canonical re-mark guard (spec §Status 状态机)."""
        _write_run(tmp_path, nnn='000010', status='done')
        with pytest.raises(schema.InvalidTransition, match="'done' → 'done'"):
            mark_cmd.mark_run(tmp_path, '10', 'done', None)

    def test_done_to_failed_rejects(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000011', status='done')
        with pytest.raises(schema.InvalidTransition):
            mark_cmd.mark_run(tmp_path, '11', 'failed', None)

    def test_failed_to_done_rejects(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000012', status='failed')
        with pytest.raises(schema.InvalidTransition):
            mark_cmd.mark_run(tmp_path, '12', 'done', None)

    def test_killed_to_done_rejects(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000013', status='killed')
        with pytest.raises(schema.InvalidTransition):
            mark_cmd.mark_run(tmp_path, '13', 'done', None)

    def test_killed_to_killed_rejects(self, tmp_path: Path) -> None:
        """Re-mark same terminal state — must still raise (frozen)."""
        _write_run(tmp_path, nnn='000014', status='killed')
        with pytest.raises(schema.InvalidTransition):
            mark_cmd.mark_run(tmp_path, '14', 'killed', None)

    def test_failed_metadata_unchanged_on_invalid_transition(self, tmp_path: Path) -> None:
        """Rejected mark must leave metadata.toml byte-for-byte unchanged."""
        run_dir = _write_run(tmp_path, nnn='000015', status='done', notes='original')
        before_bytes = (run_dir / 'metadata.toml').read_bytes()
        with pytest.raises(schema.InvalidTransition):
            mark_cmd.mark_run(tmp_path, '15', 'failed', 'should-not-be-written')
        after_bytes = (run_dir / 'metadata.toml').read_bytes()
        assert before_bytes == after_bytes


# --- Notes handling (TOML escape + preservation) ----------------------------


class TestNotes:
    def test_simple_notes_written(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000020', status='running')
        mark_cmd.mark_run(tmp_path, '20', 'done', 'hello world')
        assert _read_meta(run_dir).notes == 'hello world'

    def test_notes_omitted_preserves_existing(self, tmp_path: Path) -> None:
        """``--notes`` not provided → existing notes carry over."""
        run_dir = _write_run(tmp_path, nnn='000021', status='running', notes='preserve me')
        mark_cmd.mark_run(tmp_path, '21', 'done', None)
        meta = _read_meta(run_dir)
        assert meta.status == 'done'
        assert meta.notes == 'preserve me'

    def test_notes_empty_string_overwrites(self, tmp_path: Path) -> None:
        """Explicit ``--notes ''`` overwrites existing (empty != None)."""
        run_dir = _write_run(tmp_path, nnn='000022', status='running', notes='old')
        mark_cmd.mark_run(tmp_path, '22', 'done', '')
        assert _read_meta(run_dir).notes == ''

    def test_notes_with_newline_escaped(self, tmp_path: Path) -> None:
        """Raw ``\\n`` in notes must round-trip via TOML escape (spec §CLI mark 细则 HIGH-1-D/HIGH-6-A)."""
        run_dir = _write_run(tmp_path, nnn='000023', status='running')
        mark_cmd.mark_run(tmp_path, '23', 'done', 'line1\nline2')
        # On-disk TOML must show the escaped sequence, not a raw newline
        # inside the quoted string (which would break the basic-string grammar).
        on_disk = (run_dir / 'metadata.toml').read_text(encoding='utf-8')
        assert 'notes = "line1\\nline2"' in on_disk
        # Round-trip via tomllib must reproduce the original raw bytes.
        assert _read_meta(run_dir).notes == 'line1\nline2'

    def test_notes_with_toml_injection_escaped(self, tmp_path: Path) -> None:
        """``]\\n[other_section]`` payload must not corrupt TOML structure."""
        run_dir = _write_run(tmp_path, nnn='000024', status='running')
        payload = '"]\n[other_section]\nrun_id = "deadbe"\n'
        mark_cmd.mark_run(tmp_path, '24', 'done', payload)
        # File must still parse cleanly and notes must come back verbatim.
        meta = _read_meta(run_dir)
        assert meta.run_id == '000024'  # not 'deadbe' — injection escaped
        assert meta.notes == payload

    def test_notes_with_control_chars_escaped(self, tmp_path: Path) -> None:
        """``\\t`` / ``\\r`` round-trip via emitter escape."""
        run_dir = _write_run(tmp_path, nnn='000025', status='running')
        mark_cmd.mark_run(tmp_path, '25', 'done', 'a\tb\rc')
        assert _read_meta(run_dir).notes == 'a\tb\rc'

    def test_notes_with_backslash_escaped(self, tmp_path: Path) -> None:
        """Raw backslash must be escaped (otherwise becomes escape lead-in)."""
        run_dir = _write_run(tmp_path, nnn='000026', status='running')
        mark_cmd.mark_run(tmp_path, '26', 'done', r'path\to\file')
        assert _read_meta(run_dir).notes == r'path\to\file'

    def test_notes_with_double_quote_escaped(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000027', status='running')
        mark_cmd.mark_run(tmp_path, '27', 'done', 'she said "hi"')
        assert _read_meta(run_dir).notes == 'she said "hi"'


# --- Field preservation (mark touches only status + notes) ------------------


class TestFieldPreservation:
    def test_other_fields_unchanged(self, tmp_path: Path) -> None:
        """``wall_seconds`` / ``exit_code`` / ``timestamp`` / cfg / git / host
        / artifacts_dir / cfg_resolved_version all carry over unchanged."""
        run_dir = _write_run(
            tmp_path,
            nnn='000030',
            timestamp='2026-05-18T03:55:21+00:00',
            status='running',
        )
        before = _read_meta(run_dir)
        mark_cmd.mark_run(tmp_path, '30', 'done', 'closing manually')
        after = _read_meta(run_dir)
        # Mark touches status + notes only; everything else is invariant.
        assert after.run_id == before.run_id
        assert after.timestamp == before.timestamp
        assert after.cfg_file == before.cfg_file
        assert after.cfg_resolved_version == before.cfg_resolved_version
        assert after.git_commit == before.git_commit
        assert after.host == before.host
        assert after.artifacts_dir == before.artifacts_dir
        assert after.wall_seconds == before.wall_seconds
        assert after.exit_code == before.exit_code


# --- CLI integration (main + argparse exit codes) --------------------------


class TestCLI:
    def test_cli_subprocess_happy_path(self, tmp_path: Path) -> None:
        """End-to-end ``python -m tools.runs.mark`` exits 0."""
        _write_run(tmp_path, nnn='000040', status='running')
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.mark',
                '40',
                '--status',
                'done',
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],  # repo root
        )
        assert result.returncode == 0, f'stderr={result.stderr!r}'

    def test_cli_bad_status_argparse_rejects(self, tmp_path: Path) -> None:
        """``--status invalid`` → argparse exits non-zero (SystemExit 2 via
        argparse; not our mark_run path)."""
        _write_run(tmp_path, nnn='000041', status='running')
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.mark',
                '41',
                '--status',
                'paused',  # not in choices
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        assert result.returncode != 0

    def test_cli_invalid_transition_exits_2(self, tmp_path: Path) -> None:
        """Terminal-state mark → main() catches InvalidTransition → exit 2."""
        _write_run(tmp_path, nnn='000042', status='done')
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.mark',
                '42',
                '--status',
                'failed',
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        assert result.returncode == 2
        assert 'tools.runs.mark:' in result.stderr
        assert 'transition' in result.stderr

    def test_cli_lookup_failure_exits_2(self, tmp_path: Path) -> None:
        """0 match → main() catches LookupError → exit 2."""
        # Create artifacts/ dir so the resolver scan does not encounter
        # missing-parent error, but with no run inside.
        (tmp_path / 'artifacts').mkdir()
        result = subprocess.run(
            [
                sys.executable,
                '-m',
                'tools.runs.mark',
                '999',
                '--status',
                'done',
                '--root',
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[3],
        )
        assert result.returncode == 2
        assert 'NNN not found' in result.stderr

    def test_main_returns_2_on_invalid_transition(self, tmp_path: Path) -> None:
        """In-process main() also returns 2 on InvalidTransition (no subprocess)."""
        _write_run(tmp_path, nnn='000043', status='killed')
        rc = mark_cmd.main(['43', '--status', 'done', '--root', str(tmp_path)])
        assert rc == 2

    def test_main_returns_0_on_success(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000044', status='running')
        rc = mark_cmd.main(['44', '--status', 'done', '--root', str(tmp_path)])
        assert rc == 0

    def test_main_passes_notes_through(self, tmp_path: Path) -> None:
        run_dir = _write_run(tmp_path, nnn='000045', status='running')
        rc = mark_cmd.main(['45', '--status', 'done', '--notes', 'CLI note', '--root', str(tmp_path)])
        assert rc == 0
        assert _read_meta(run_dir).notes == 'CLI note'


# --- Defense-in-depth: bypass argparse (caller-bug guard) ------------------


class TestDirectAPIGuards:
    def test_mark_run_rejects_invalid_target_status(self, tmp_path: Path) -> None:
        """Direct API caller passing a non-target status (e.g. ``'running'``
        or ``'unknown'``) is a caller bug — argparse choices=... should
        normally reject earlier, but mark_run defends in depth (spec
        §Status 状态机 allows 3 mark targets only)."""
        _write_run(tmp_path, nnn='000050', status='running')
        with pytest.raises(ValueError, match='mark target'):
            mark_cmd.mark_run(tmp_path, '50', 'running', None)

    def test_mark_run_rejects_unknown_target_status(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000051', status='running')
        with pytest.raises(ValueError, match='mark target'):
            mark_cmd.mark_run(tmp_path, '51', 'unknown', None)

    def test_mark_run_rejects_garbage_target_status(self, tmp_path: Path) -> None:
        _write_run(tmp_path, nnn='000052', status='running')
        with pytest.raises(ValueError, match='mark target'):
            mark_cmd.mark_run(tmp_path, '52', 'wat', None)


# --- Atomic write: lock + temp + rename --------------------------------------


class TestAtomicWrite:
    def test_no_temp_file_left_after_success(self, tmp_path: Path) -> None:
        """Successful mark must clean up ``metadata.toml.tmp`` (it was
        renamed to the target — no leftover)."""
        run_dir = _write_run(tmp_path, nnn='000060', status='running')
        mark_cmd.mark_run(tmp_path, '60', 'done', None)
        assert not (run_dir / 'metadata.toml.tmp').exists()
        assert (run_dir / 'metadata.toml').exists()

    def test_metadata_lock_file_created(self, tmp_path: Path) -> None:
        """``.metadata_lock`` sentinel file created during the mark
        (kernel auto-releases on fd close, file itself persists)."""
        run_dir = _write_run(tmp_path, nnn='000061', status='running')
        mark_cmd.mark_run(tmp_path, '61', 'done', None)
        assert (run_dir / '.metadata_lock').is_file()

    def test_post_mark_file_is_valid_toml(self, tmp_path: Path) -> None:
        """Post-mark metadata.toml must be a complete, parseable record
        (no partial / truncated writes)."""
        run_dir = _write_run(tmp_path, nnn='000062', status='running', notes='before')
        mark_cmd.mark_run(tmp_path, '62', 'killed', 'after')
        meta = _read_meta(run_dir)  # would raise on parse failure
        assert meta.status == 'killed'
        assert meta.notes == 'after'
