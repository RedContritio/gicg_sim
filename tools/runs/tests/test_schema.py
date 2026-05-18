"""Schema tests for tools.runs.schema (clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``).

Covers: 11-field RunMetadata field-level validation (each raise path),
status enum (5 values incl. ``unknown``), ``validate_transition`` matrix
incl. resume exception (CRIT-2-A), TOML round-trip, file save/load.
"""

from __future__ import annotations

import sys

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from tools.runs import schema


def _minimal_meta(**overrides) -> schema.RunMetadata:
    """Build a minimally-valid RunMetadata for tests."""
    defaults = dict(
        run_id='000069',
        timestamp='2026-05-18T03:55:21+00:00',
        cfg_file='configs/dmc/smoke_full.toml',
        cfg_resolved_version=1,
        git_commit='2c20de8a',
        host='Mac-mini.local',
        status='running',
        artifacts_dir='artifacts/202605180355_000069_dmc_smoke_full',
        wall_seconds=0.0,
        exit_code=0,
        notes='',
    )
    defaults.update(overrides)
    return schema.RunMetadata(**defaults)


class TestStatusEnum:
    def test_exactly_five_values(self):
        """spec §Status 状态机: enum is {running, done, failed, killed, unknown};
        no 'pending' (pre-redesign value retired)."""
        assert schema.STATUSES == frozenset({'running', 'done', 'failed', 'killed', 'unknown'})

    def test_terminal_statuses_exactly_three(self):
        assert schema.TERMINAL_STATUSES == frozenset({'done', 'failed', 'killed'})


class TestRunId:
    @pytest.mark.parametrize('rid', ['000000', '000069', '999999'])
    def test_accepts_six_digit_zero_pad(self, rid):
        schema.validate(_minimal_meta(run_id=rid))

    @pytest.mark.parametrize(
        'bad',
        [
            'r013',  # pre-redesign 3-digit r-prefix
            's068',  # pre-redesign 3-digit s-prefix
            '69',  # too short
            '00069',  # 5 digits
            '0000069',  # 7 digits
            '00006a',  # alpha char
        ],
    )
    def test_rejects(self, bad):
        with pytest.raises(ValueError, match='run_id'):
            schema.validate(_minimal_meta(run_id=bad))

    def test_rejects_non_string(self):
        with pytest.raises(ValueError, match='run_id'):
            schema.validate(_minimal_meta(run_id=69))  # type: ignore[arg-type]


class TestFieldValidation:
    def test_rejects_empty_timestamp(self):
        with pytest.raises(ValueError, match='timestamp'):
            schema.validate(_minimal_meta(timestamp=''))

    def test_rejects_non_string_timestamp(self):
        with pytest.raises(ValueError, match='timestamp'):
            schema.validate(_minimal_meta(timestamp=12345))  # type: ignore[arg-type]

    def test_rejects_empty_cfg_file(self):
        with pytest.raises(ValueError, match='cfg_file'):
            schema.validate(_minimal_meta(cfg_file=''))

    @pytest.mark.parametrize('bad', [0, -1, 1.0, True])
    def test_rejects_bad_cfg_resolved_version(self, bad):
        with pytest.raises(ValueError, match='cfg_resolved_version'):
            schema.validate(_minimal_meta(cfg_resolved_version=bad))

    def test_accepts_cfg_resolved_version_high(self):
        schema.validate(_minimal_meta(cfg_resolved_version=42))

    def test_rejects_empty_git_commit(self):
        with pytest.raises(ValueError, match='git_commit'):
            schema.validate(_minimal_meta(git_commit=''))

    def test_accepts_unknown_git_commit(self):
        """spec says use 'unknown' literal when unavailable."""
        schema.validate(_minimal_meta(git_commit='unknown'))

    def test_rejects_empty_host(self):
        with pytest.raises(ValueError, match='host'):
            schema.validate(_minimal_meta(host=''))

    @pytest.mark.parametrize('bad', ['ongoing', 'pending'])
    def test_rejects_bad_status(self, bad):
        """'pending' was in the pre-redesign enum and is removed."""
        with pytest.raises(ValueError, match='status'):
            schema.validate(_minimal_meta(status=bad))

    @pytest.mark.parametrize('s', sorted(schema.STATUSES))
    def test_accepts_each_status(self, s):
        schema.validate(_minimal_meta(status=s))

    def test_rejects_empty_artifacts_dir(self):
        with pytest.raises(ValueError, match='artifacts_dir'):
            schema.validate(_minimal_meta(artifacts_dir=''))

    @pytest.mark.parametrize('bad', [-1.0, '16.3', True])
    def test_rejects_bad_wall_seconds(self, bad):
        with pytest.raises(ValueError, match='wall_seconds'):
            schema.validate(_minimal_meta(wall_seconds=bad))

    @pytest.mark.parametrize('ok', [0.0, 0, 42, 84.3])
    def test_accepts_wall_seconds(self, ok):
        schema.validate(_minimal_meta(wall_seconds=ok))

    @pytest.mark.parametrize('bad', ['0', True])
    def test_rejects_bad_exit_code(self, bad):
        with pytest.raises(ValueError, match='exit_code'):
            schema.validate(_minimal_meta(exit_code=bad))

    def test_accepts_exit_code_3(self):
        """spec §Exit codes lists 0/1/2/3 — schema does not constrain set."""
        schema.validate(_minimal_meta(exit_code=3))

    def test_rejects_non_string_notes(self):
        with pytest.raises(ValueError, match='notes'):
            schema.validate(_minimal_meta(notes=None))  # type: ignore[arg-type]

    @pytest.mark.parametrize('ok', ['', 'line1\nline2'])
    def test_accepts_notes(self, ok):
        schema.validate(_minimal_meta(notes=ok))


class TestValidateTransitionNormal:
    """Normal (resume=False) transitions per spec §Status 状态机."""

    @pytest.mark.parametrize(
        ('old', 'new'),
        [
            ('running', 'done'),
            ('running', 'failed'),
            ('running', 'killed'),
            ('running', 'running'),  # idempotent write
            ('unknown', 'done'),
            ('unknown', 'failed'),
            ('unknown', 'killed'),
        ],
    )
    def test_allowed(self, old, new):
        schema.validate_transition(old, new)

    @pytest.mark.parametrize(
        ('old', 'new'),
        [
            # Terminal → anything (default): forbidden
            ('done', 'running'),
            ('done', 'failed'),
            ('done', 'killed'),
            ('done', 'done'),
            ('done', 'unknown'),
            ('failed', 'running'),
            ('failed', 'done'),
            ('failed', 'killed'),
            ('failed', 'failed'),
            ('failed', 'unknown'),
            ('killed', 'running'),
            ('killed', 'done'),
            ('killed', 'failed'),
            ('killed', 'killed'),
            ('killed', 'unknown'),
            # unknown → running / unknown: forbidden without resume
            ('unknown', 'running'),
            ('unknown', 'unknown'),
            # running → unknown: forbidden (recover only writes unknown for
            # rebuilt dirs that had no metadata at all)
            ('running', 'unknown'),
        ],
    )
    def test_forbidden(self, old, new):
        with pytest.raises(schema.InvalidTransition):
            schema.validate_transition(old, new)

    def test_invalid_transition_subclass_of_value_error(self):
        """Callers may catch ValueError generically."""
        assert issubclass(schema.InvalidTransition, ValueError)


class TestValidateTransitionResumeException:
    """Resume exception CRIT-2-A: ``{done,failed,killed,unknown} → running``
    is allowed only when ``resume=True``."""

    @pytest.mark.parametrize('old', ['done', 'failed', 'killed', 'unknown'])
    def test_resume_into_running(self, old):
        schema.validate_transition(old, 'running', resume=True)

    def test_resume_running_to_running_no_op_allowed(self):
        """spec line 243: resume sees metadata already 'running' → no-op
        warn; schema layer allows it."""
        schema.validate_transition('running', 'running', resume=True)

    @pytest.mark.parametrize('old', ['done', 'failed', 'killed', 'unknown'])
    def test_into_running_without_resume_forbidden(self, old):
        """Critical: resume exception must NOT leak into the default path."""
        with pytest.raises(schema.InvalidTransition):
            schema.validate_transition(old, 'running')

    @pytest.mark.parametrize(
        ('old', 'new'),
        [
            # resume does NOT permit transitions into non-running targets
            # ('mark' handles those; resume only flips into running).
            ('done', 'failed'),
            ('done', 'killed'),
            ('failed', 'done'),
            ('killed', 'done'),
            ('done', 'unknown'),
            ('failed', 'unknown'),
            ('killed', 'unknown'),
            ('running', 'unknown'),
        ],
    )
    def test_resume_does_not_relax_non_running_targets(self, old, new):
        with pytest.raises(schema.InvalidTransition):
            schema.validate_transition(old, new, resume=True)


class TestValidateTransitionEnumGuards:
    def test_rejects_bad_old(self):
        with pytest.raises(ValueError, match='old status'):
            schema.validate_transition('pending', 'done')

    def test_rejects_bad_new(self):
        with pytest.raises(ValueError, match='new status'):
            schema.validate_transition('running', 'pending')

    def test_rejects_bad_new_even_with_resume(self):
        with pytest.raises(ValueError, match='new status'):
            schema.validate_transition('done', 'pending', resume=True)


def _full_dict(m: schema.RunMetadata) -> dict:
    return {
        'run_id': m.run_id,
        'timestamp': m.timestamp,
        'cfg_file': m.cfg_file,
        'cfg_resolved_version': m.cfg_resolved_version,
        'git_commit': m.git_commit,
        'host': m.host,
        'status': m.status,
        'artifacts_dir': m.artifacts_dir,
        'wall_seconds': m.wall_seconds,
        'exit_code': m.exit_code,
        'notes': m.notes,
    }


class TestFromDict:
    def test_missing_required_keys_raises(self):
        with pytest.raises(ValueError, match='missing required keys'):
            schema.from_dict({'run_id': '000069'})

    def test_missing_each_field_raises(self):
        """Cross-check: every field, when omitted, raises missing-keys."""
        full = _full_dict(_minimal_meta())
        for k in list(full.keys()):
            partial = {kk: vv for kk, vv in full.items() if kk != k}
            with pytest.raises(ValueError, match='missing required keys'):
                schema.from_dict(partial)

    def test_unknown_key_raises(self):
        """Stale fields (removed ``paradigm``, ``cfg_checksum``) must not be
        silently dropped — they signal a stale / corrupt metadata file."""
        d = _full_dict(_minimal_meta())
        d['paradigm'] = 'az'  # removed field
        with pytest.raises(ValueError, match='unknown keys'):
            schema.from_dict(d)

    def test_round_trip_via_dict(self):
        m = _minimal_meta()
        assert schema.from_dict(_full_dict(m)) == m


class TestDumpsLoads:
    def test_minimal_round_trip(self):
        m = _minimal_meta()
        assert schema.loads(schema.dumps(m)) == m

    def test_terminal_status_round_trip(self):
        m = _minimal_meta(status='done', wall_seconds=84.3, exit_code=0, notes='ok')
        assert schema.loads(schema.dumps(m)) == m

    def test_unknown_status_round_trips(self):
        """recover writes status='unknown'; must survive round-trip."""
        m = _minimal_meta(status='unknown')
        assert schema.loads(schema.dumps(m)).status == 'unknown'

    def test_field_order_in_emitted_toml(self):
        """Stable field order for diff-friendly metadata."""
        text = schema.dumps(_minimal_meta())
        keys_in_order = [line.split(' = ', 1)[0] for line in text.strip().split('\n')]
        assert keys_in_order == list(schema._FIELD_ORDER)

    def test_emitted_toml_parses_via_tomllib(self):
        m = _minimal_meta(wall_seconds=84.3, exit_code=1, notes='x')
        parsed = tomllib.loads(schema.dumps(m))
        assert parsed['run_id'] == m.run_id
        assert parsed['wall_seconds'] == pytest.approx(84.3)
        assert parsed['exit_code'] == 1

    def test_notes_with_quotes_and_backslash_round_trip(self):
        m = _minimal_meta(notes='line1\nline2 with "quote" and \\ backslash\ttab')
        assert schema.loads(schema.dumps(m)).notes == m.notes

    def test_wall_seconds_float_round_trip_precision(self):
        m = _minimal_meta(wall_seconds=1234.5678)
        assert schema.loads(schema.dumps(m)).wall_seconds == pytest.approx(1234.5678)

    def test_wall_seconds_int_in_toml_loads_as_float(self):
        """tomllib gives int for ``wall_seconds = 0`` — must coerce."""
        toml_text = (
            'run_id = "000069"\n'
            'timestamp = "2026-05-18T03:55:21+00:00"\n'
            'cfg_file = "x.toml"\n'
            'cfg_resolved_version = 1\n'
            'git_commit = "abc"\n'
            'host = "h"\n'
            'status = "running"\n'
            'artifacts_dir = "artifacts/d"\n'
            'wall_seconds = 0\n'
            'exit_code = 0\n'
            'notes = ""\n'
        )
        m = schema.loads(toml_text)
        assert isinstance(m.wall_seconds, float)
        assert m.wall_seconds == 0.0


class TestSaveLoadFile:
    def test_save_creates_parent_dir_and_load_round_trips(self, tmp_path):
        m = _minimal_meta()
        path = tmp_path / 'deep' / 'nested' / 'metadata.toml'
        schema.save_file(m, path)
        assert path.exists()
        assert schema.load_file(path) == m

    def test_load_file_no_filename_invariant(self, tmp_path):
        """Per spec, the metadata file is always named ``metadata.toml``
        inside the artifacts dir; there is no run_id-vs-filename check
        (that invariant was for the retired ``artifacts/runs/<NNN>.toml``
        layout)."""
        m = _minimal_meta(run_id='000069')
        path = tmp_path / 'arbitrary_name.toml'  # deliberately wrong-looking
        schema.save_file(m, path)
        assert schema.load_file(path) == m

    def test_save_file_rejects_invalid_and_does_not_write(self, tmp_path):
        """save_file calls dumps → validate; invalid meta must not write."""
        path = tmp_path / 'metadata.toml'
        bad = _minimal_meta(status='pending')
        with pytest.raises(ValueError):
            schema.save_file(bad, path)
        assert not path.exists()
