"""Smoke tests for tools.runs.list CLI."""

from __future__ import annotations

import datetime

import pytest

from tools.runs import list as list_cmd
from tools.runs import register


def _register(root, *, run_id, paradigm='az', description='', type_=None):
    cfg = root / f'{run_id}_cfg.toml'
    cfg.write_text(f'paradigm = "{paradigm}"\n', encoding='utf-8')
    return register.register(
        run_id=run_id,
        cfg_file=str(cfg),
        type_=type_,
        description=description,
        root=root,
        now=datetime.datetime(2026, 5, 17, 14, 0, 0, tzinfo=datetime.timezone.utc),
        host='h',
        git_commit='abc',
    )


def test_list_empty_runs_dir(tmp_path, capsys):
    rc = list_cmd.main(['--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'no runs found' in out


def test_list_missing_runs_dir(tmp_path, capsys):
    # tmp_path/artifacts/runs/ doesn't exist yet — should be friendly, not crash.
    rc = list_cmd.main(['--root', str(tmp_path / 'fresh')])
    assert rc == 0
    assert 'no runs found' in capsys.readouterr().out


def test_list_one_record(tmp_path, capsys):
    _register(tmp_path, run_id='r013', description='AZ stage 3')
    rc = list_cmd.main(['--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'r013' in out
    assert 'az' in out
    assert 'pending' in out
    assert 'AZ stage 3' in out


def test_list_multiple_sorted(tmp_path, capsys):
    _register(tmp_path, run_id='r014', paradigm='ppo')
    _register(tmp_path, run_id='r013', paradigm='az')
    _register(tmp_path, run_id='s068', paradigm='dmc', type_='s')
    rc = list_cmd.main(['--root', str(tmp_path)])
    assert rc == 0
    out = capsys.readouterr().out
    # r013 should appear before r014 (lexicographic sort).
    pos_r013 = out.find('r013')
    pos_r014 = out.find('r014')
    pos_s068 = out.find('s068')
    assert pos_r013 != -1 and pos_r014 != -1 and pos_s068 != -1
    assert pos_r013 < pos_r014 < pos_s068


def test_list_filter_by_type_r(tmp_path, capsys):
    _register(tmp_path, run_id='r013')
    _register(tmp_path, run_id='s068', type_='s')
    rc = list_cmd.main(['--root', str(tmp_path), '--type', 'r'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 'r013' in out
    assert 's068' not in out


def test_list_filter_by_type_s(tmp_path, capsys):
    _register(tmp_path, run_id='r013')
    _register(tmp_path, run_id='s068', type_='s')
    rc = list_cmd.main(['--root', str(tmp_path), '--type', 's'])
    assert rc == 0
    out = capsys.readouterr().out
    assert 's068' in out
    assert 'r013' not in out


def test_list_skips_malformed_file(tmp_path, capsys):
    """A file that fails to parse should be reported on stderr but not
    crash the whole listing."""
    _register(tmp_path, run_id='r013')
    bad = tmp_path / 'artifacts' / 'runs' / 's069.toml'
    bad.write_text('not = a [ valid toml ]] file', encoding='utf-8')
    rc = list_cmd.main(['--root', str(tmp_path)])
    assert rc == 0
    captured = capsys.readouterr()
    assert 'r013' in captured.out
    assert 'skipping' in captured.err
    assert 's069' in captured.err


def test_render_table_headers(tmp_path):
    meta = _register(tmp_path, run_id='r013')
    table = list_cmd.render_table([meta])
    assert 'run_id' in table
    assert 'paradigm' in table
    assert 'status' in table
    assert 'wall' in table


def test_render_table_truncates_long_description(tmp_path):
    long = 'a' * 200
    meta = _register(tmp_path, run_id='r013', description=long)
    table = list_cmd.render_table([meta])
    # Should not contain the full 200-char description (truncated to ~60).
    assert long not in table


def test_render_table_first_sentence_only(tmp_path):
    desc = 'First sentence. Second sentence we should not see.'
    meta = _register(tmp_path, run_id='r013', description=desc)
    table = list_cmd.render_table([meta])
    assert 'First sentence' in table
    assert 'Second sentence' not in table
