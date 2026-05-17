"""Smoke tests for tools.runs.complete CLI."""

from __future__ import annotations

import datetime
import json

import pytest

from tools.runs import complete, register, schema


@pytest.fixture
def registered_run(tmp_path):
    """A pre-registered r013 record on disk under tmp_path."""
    cfg = tmp_path / 'r013.toml'
    cfg.write_text('[meta]\nparadigm = "az"\nrun_label = "r013_test"\n', encoding='utf-8')
    register.register(
        run_id='r013',
        cfg_file=str(cfg),
        root=tmp_path,
        now=datetime.datetime(2026, 5, 17, 14, 0, 0, tzinfo=datetime.timezone.utc),
        host='h',
        git_commit='abc',
    )
    return tmp_path


def test_complete_done_status_only(registered_run):
    meta = complete.complete(run_id='r013', status='done', root=registered_run)
    assert meta.status == 'done'


def test_complete_failed_status(registered_run):
    meta = complete.complete(run_id='r013', status='failed', root=registered_run)
    assert meta.status == 'failed'


def test_complete_killed_status(registered_run):
    meta = complete.complete(run_id='r013', status='killed', root=registered_run)
    assert meta.status == 'killed'


def test_complete_with_wall_and_notes(registered_run):
    meta = complete.complete(
        run_id='r013',
        status='done',
        wall='16.3min',
        notes='solid run, baseline matched',
        root=registered_run,
    )
    assert meta.summary.wall == '16.3min'
    assert meta.notes.text == 'solid run, baseline matched'


def test_complete_with_gauntlet_json(registered_run, tmp_path):
    g_path = tmp_path / 'gauntlet.json'
    g_path.write_text(
        json.dumps(
            {
                'n': 16,
                'results': {'random': 0.875, 'mcts_pure_200': 0.5625},
            }
        ),
        encoding='utf-8',
    )
    meta = complete.complete(
        run_id='r013',
        status='done',
        gauntlet_json=str(g_path),
        root=registered_run,
    )
    assert meta.result.gauntlet is not None
    assert meta.result.gauntlet.n == 16
    assert meta.result.gauntlet.metrics['random'] == pytest.approx(0.875)
    assert meta.result.gauntlet.metrics['mcts_pure_200'] == pytest.approx(0.5625)


def test_complete_with_training_block(registered_run):
    meta = complete.complete(
        run_id='r013',
        status='done',
        final_loss=1.045,
        n_games=400,
        root=registered_run,
    )
    assert meta.result.training is not None
    assert meta.result.training.final_loss == pytest.approx(1.045)
    assert meta.result.training.n_games_completed == 400


def test_complete_partial_training_block(registered_run):
    """Setting only final_loss should populate that field + leave
    n_games_completed at default 0 (new block created)."""
    meta = complete.complete(
        run_id='r013',
        status='done',
        final_loss=0.5,
        root=registered_run,
    )
    assert meta.result.training is not None
    assert meta.result.training.final_loss == pytest.approx(0.5)
    assert meta.result.training.n_games_completed == 0


def test_complete_idempotent_persist(registered_run):
    """After complete, re-load file and confirm status + result block
    survive a fresh load_file cycle."""
    complete.complete(
        run_id='r013',
        status='done',
        wall='5min',
        root=registered_run,
    )
    on_disk = schema.load_file(schema.run_path('r013', root=registered_run))
    assert on_disk.status == 'done'
    assert on_disk.summary.wall == '5min'


def test_complete_rejects_missing_record(tmp_path):
    with pytest.raises(FileNotFoundError):
        complete.complete(run_id='r999', status='done', root=tmp_path)


def test_complete_rejects_bad_status(registered_run):
    with pytest.raises(ValueError, match='status'):
        complete.complete(run_id='r013', status='ongoing', root=registered_run)


def test_complete_rejects_missing_gauntlet_json(registered_run, tmp_path):
    with pytest.raises(FileNotFoundError):
        complete.complete(
            run_id='r013',
            status='done',
            gauntlet_json=str(tmp_path / 'nope.json'),
            root=registered_run,
        )


def test_complete_rejects_malformed_gauntlet_json(registered_run, tmp_path):
    g_path = tmp_path / 'bad.json'
    g_path.write_text('not valid json {{', encoding='utf-8')
    with pytest.raises(ValueError, match='malformed'):
        complete.complete(
            run_id='r013',
            status='done',
            gauntlet_json=str(g_path),
            root=registered_run,
        )


def test_complete_rejects_gauntlet_json_missing_n(registered_run, tmp_path):
    g_path = tmp_path / 'no_n.json'
    g_path.write_text(json.dumps({'results': {'random': 0.5}}), encoding='utf-8')
    with pytest.raises(ValueError, match='"n"'):
        complete.complete(
            run_id='r013',
            status='done',
            gauntlet_json=str(g_path),
            root=registered_run,
        )


def test_complete_cli_main_happy(registered_run, capsys):
    rc = complete.main(
        [
            '--run-id',
            'r013',
            '--status',
            'done',
            '--root',
            str(registered_run),
        ]
    )
    assert rc == 0
    out = capsys.readouterr().out
    assert 'r013' in out and 'done' in out


def test_complete_cli_main_error(tmp_path, capsys):
    rc = complete.main(
        [
            '--run-id',
            'r999',
            '--status',
            'done',
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 1
    assert 'tools.runs.complete' in capsys.readouterr().err
