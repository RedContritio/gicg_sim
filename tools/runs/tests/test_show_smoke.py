"""Smoke tests for tools.runs.show CLI."""

from __future__ import annotations

import datetime

import pytest

from tools.runs import complete, register, schema, show


def _register(root, *, run_id='r013', paradigm='az', description=''):
    cfg = root / f'{run_id}_cfg.toml'
    cfg.write_text(f'paradigm = "{paradigm}"\n', encoding='utf-8')
    return register.register(
        run_id=run_id,
        cfg_file=str(cfg),
        description=description,
        root=root,
        now=datetime.datetime(2026, 5, 17, 14, 0, 0, tzinfo=datetime.timezone.utc),
        host='test-host',
        git_commit='deadbeef',
    )


def test_show_basic(tmp_path, capsys):
    _register(tmp_path, description='AZ stage 3 smoke')
    rc = show.main(['r013', '--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'run_id       : r013' in out
    assert 'paradigm     : az' in out
    assert 'status       : pending' in out
    assert 'host         : test-host' in out
    assert 'git_commit   : deadbeef' in out
    assert 'AZ stage 3 smoke' in out


def test_show_includes_raw_toml(tmp_path, capsys):
    _register(tmp_path)
    rc = show.main(['r013', '--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '--- raw toml ---' in out
    # Raw toml block should contain the key=value form.
    assert 'run_id = "r013"' in out


def test_show_toml_only(tmp_path, capsys):
    _register(tmp_path)
    rc = show.main(['r013', '--root', str(tmp_path), '--toml-only'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'run_id = "r013"' in out
    # Human-readable header lines should NOT appear in toml-only mode.
    assert 'run_id       :' not in out


def test_show_with_gauntlet_block(tmp_path, capsys):
    import json

    _register(tmp_path)
    g_path = tmp_path / 'g.json'
    g_path.write_text(json.dumps({'n': 16, 'results': {'random': 0.875}}), encoding='utf-8')
    complete.complete(
        run_id='r013',
        status='done',
        gauntlet_json=str(g_path),
        root=tmp_path,
    )
    rc = show.main(['r013', '--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '[result.gauntlet] n=16' in out
    assert 'random: 0.8750' in out


def test_show_with_training_block(tmp_path, capsys):
    _register(tmp_path)
    complete.complete(
        run_id='r013',
        status='done',
        final_loss=1.045,
        n_games=400,
        root=tmp_path,
    )
    rc = show.main(['r013', '--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '[result.training]' in out
    assert 'final_loss=1.0450' in out
    assert 'n_games_completed=400' in out


def test_show_with_notes(tmp_path, capsys):
    _register(tmp_path)
    complete.complete(run_id='r013', status='done', notes='ran overnight', root=tmp_path)
    rc = show.main(['r013', '--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '[notes] ran overnight' in out


def test_show_missing_run(tmp_path, capsys):
    rc = show.main(['r999', '--root', str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert 'not registered' in err


def test_show_corrupted_record(tmp_path, capsys):
    bad = schema.runs_dir(tmp_path) / 'r013.toml'
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text('not = a [ valid toml }} file', encoding='utf-8')
    rc = show.main(['r013', '--root', str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert 'tools.runs.show' in err


def test_render_function_no_optional_blocks(tmp_path):
    """render() pure-function — invoke directly for assertion.

    `[notes]` always appears in the raw-toml dump (schema always emits
    `[notes]` with empty text) — only check the human-readable section
    (before `--- raw toml ---`) for it.
    """
    meta = _register(tmp_path)
    text = show.render(meta)
    human, _, _raw = text.partition('--- raw toml ---')
    assert 'run_id       : r013' in human
    assert '[result.gauntlet]' not in human
    assert '[result.training]' not in human
    assert '[notes]' not in human
