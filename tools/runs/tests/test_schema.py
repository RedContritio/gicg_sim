"""Schema validation + TOML round-trip tests for tools.runs.schema."""

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
        run_id='r013',
        label='r013_test',
        type='r',
        timestamp='2026-05-17T14:00:00+00:00',
        paradigm='az',
        cfg_file='configs/az/runs/r013.toml',
        cfg_checksum='sha256:' + 'a' * 64,
        cfg_run_label='r013_test',
        git_commit='abc123def456',
        host='test-host',
        status='pending',
    )
    defaults.update(overrides)
    return schema.RunMetadata(**defaults)


class TestValidateRunId:
    def test_valid_r_prefix(self):
        schema.validate(_minimal_meta(run_id='r013', type='r'))

    def test_valid_s_prefix(self):
        schema.validate(_minimal_meta(run_id='s068', type='s'))

    def test_rejects_no_prefix(self):
        with pytest.raises(ValueError, match='run_id'):
            schema.validate(_minimal_meta(run_id='013'))

    def test_rejects_wrong_prefix(self):
        with pytest.raises(ValueError, match='run_id'):
            schema.validate(_minimal_meta(run_id='x013'))

    def test_rejects_short_number(self):
        with pytest.raises(ValueError, match='run_id'):
            schema.validate(_minimal_meta(run_id='r13'))

    def test_rejects_long_number(self):
        with pytest.raises(ValueError, match='run_id'):
            schema.validate(_minimal_meta(run_id='r0013'))

    def test_rejects_prefix_type_mismatch(self):
        # run_id says 'r' but type says 's'
        with pytest.raises(ValueError, match='disagrees'):
            schema.validate(_minimal_meta(run_id='r013', type='s'))


class TestValidateEnums:
    def test_rejects_bad_type(self):
        # Bypass run_id-vs-type cross-check by using a valid run_id whose
        # prefix matches the bad type letter; the type-enum check fires
        # before the cross-check because the run_id regex requires r|s.
        # So we test by mutating type AFTER construction.
        m = _minimal_meta()
        m.type = 'x'
        with pytest.raises(ValueError, match='type'):
            schema.validate(m)

    def test_rejects_bad_paradigm(self):
        with pytest.raises(ValueError, match='paradigm'):
            schema.validate(_minimal_meta(paradigm='dqn'))

    def test_rejects_bad_status(self):
        with pytest.raises(ValueError, match='status'):
            schema.validate(_minimal_meta(status='ongoing'))

    @pytest.mark.parametrize('p', sorted(schema.PARADIGMS))
    def test_accepts_each_paradigm(self, p):
        schema.validate(_minimal_meta(paradigm=p))

    @pytest.mark.parametrize('s', sorted(schema.STATUSES))
    def test_accepts_each_status(self, s):
        schema.validate(_minimal_meta(status=s))


class TestValidateRequiredFields:
    def test_rejects_empty_label(self):
        with pytest.raises(ValueError, match='label'):
            schema.validate(_minimal_meta(label=''))

    def test_rejects_empty_timestamp(self):
        with pytest.raises(ValueError, match='timestamp'):
            schema.validate(_minimal_meta(timestamp=''))

    def test_rejects_empty_cfg_file(self):
        with pytest.raises(ValueError, match='cfg_file'):
            schema.validate(_minimal_meta(cfg_file=''))

    def test_rejects_empty_git_commit(self):
        with pytest.raises(ValueError, match='git_commit'):
            schema.validate(_minimal_meta(git_commit=''))

    def test_rejects_empty_host(self):
        with pytest.raises(ValueError, match='host'):
            schema.validate(_minimal_meta(host=''))


class TestValidateChecksum:
    def test_rejects_no_prefix(self):
        with pytest.raises(ValueError, match='cfg_checksum'):
            schema.validate(_minimal_meta(cfg_checksum='a' * 64))

    def test_rejects_short_hex(self):
        with pytest.raises(ValueError, match='cfg_checksum'):
            schema.validate(_minimal_meta(cfg_checksum='sha256:abc'))

    def test_rejects_uppercase_hex(self):
        with pytest.raises(ValueError, match='cfg_checksum'):
            schema.validate(_minimal_meta(cfg_checksum='sha256:' + 'A' * 64))


class TestRoundTrip:
    def test_minimal_dumps_loads(self):
        m1 = _minimal_meta()
        text = schema.dumps(m1)
        m2 = schema.loads(text)
        assert m1 == m2

    def test_with_summary_and_notes(self):
        m1 = _minimal_meta()
        m1.summary = schema.Summary(wall='16.3min', description='AZ stage 3 reproducibility check')
        m1.notes = schema.Notes(text='ran on macbook 9pm')
        text = schema.dumps(m1)
        m2 = schema.loads(text)
        assert m1 == m2

    def test_with_gauntlet_block(self):
        m1 = _minimal_meta()
        m1.result.gauntlet = schema.GauntletResult(n=16, metrics={'random': 0.875, 'mcts_pure_200': 0.5625})
        text = schema.dumps(m1)
        m2 = schema.loads(text)
        assert m2.result.gauntlet is not None
        assert m2.result.gauntlet.n == 16
        assert m2.result.gauntlet.metrics['random'] == pytest.approx(0.875)
        assert m2.result.gauntlet.metrics['mcts_pure_200'] == pytest.approx(0.5625)

    def test_with_training_block(self):
        m1 = _minimal_meta()
        m1.result.training = schema.TrainingResult(final_loss=1.045, n_games_completed=400)
        text = schema.dumps(m1)
        m2 = schema.loads(text)
        assert m2.result.training is not None
        assert m2.result.training.final_loss == pytest.approx(1.045)
        assert m2.result.training.n_games_completed == 400

    def test_with_both_result_blocks(self):
        m1 = _minimal_meta()
        m1.result.gauntlet = schema.GauntletResult(n=8, metrics={'opp_a': 0.5})
        m1.result.training = schema.TrainingResult(final_loss=0.5, n_games_completed=100)
        text = schema.dumps(m1)
        m2 = schema.loads(text)
        assert m1 == m2

    def test_optional_blocks_omitted_when_unset(self):
        m1 = _minimal_meta()
        text = schema.dumps(m1)
        # raw parse: should NOT contain [result.gauntlet] / [result.training]
        parsed = tomllib.loads(text)
        assert 'result' not in parsed  # no result table emitted

    def test_string_with_special_chars_round_trips(self):
        m1 = _minimal_meta()
        m1.notes = schema.Notes(text='line1\nline2 with "quote" and \\ backslash')
        text = schema.dumps(m1)
        m2 = schema.loads(text)
        assert m2.notes.text == m1.notes.text


class TestFromDict:
    def test_missing_required_keys(self):
        with pytest.raises(ValueError, match='missing required keys'):
            schema.from_dict({'run_id': 'r001'})

    def test_accepts_full_payload(self):
        m = _minimal_meta()
        text = schema.dumps(m)
        parsed = tomllib.loads(text)
        assert schema.from_dict(parsed) == m


class TestRunPath:
    def test_default_root(self):
        p = schema.run_path('r013')
        assert p.name == 'r013.toml'
        assert p.parent.name == 'runs'

    def test_override_root(self, tmp_path):
        p = schema.run_path('s068', root=tmp_path)
        assert p == tmp_path / 'artifacts' / 'runs' / 's068.toml'

    def test_rejects_bad_id(self):
        with pytest.raises(ValueError):
            schema.run_path('bad-id')


class TestSaveLoadFile:
    def test_save_creates_parent_dir(self, tmp_path):
        m = _minimal_meta()
        path = tmp_path / 'deep' / 'nested' / 'r013.toml'
        schema.save_file(m, path)
        assert path.exists()
        m2 = schema.load_file(path)
        assert m == m2
