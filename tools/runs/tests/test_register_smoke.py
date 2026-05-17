"""Smoke tests for tools.runs.register CLI."""

from __future__ import annotations

import datetime

import pytest

from tools.runs import register, schema


@pytest.fixture
def cfg_file(tmp_path):
    """A minimal valid cfg TOML with top-level paradigm."""
    p = tmp_path / 'r013.toml'
    p.write_text('paradigm = "az"\nversion = "1.0.0"\n', encoding='utf-8')
    return p


@pytest.fixture
def cfg_file_no_paradigm(tmp_path):
    """A cfg TOML without the top-level paradigm field."""
    p = tmp_path / 'broken.toml'
    p.write_text('version = "1.0.0"\n', encoding='utf-8')
    return p


def _fixed_now() -> datetime.datetime:
    return datetime.datetime(2026, 5, 17, 14, 0, 0, tzinfo=datetime.timezone.utc)


def test_register_happy_path(tmp_path, cfg_file):
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        root=tmp_path,
        now=_fixed_now(),
        host='test-host',
        git_commit='deadbeef',
    )
    assert meta.run_id == 'r013'
    assert meta.label == 'r013'  # default
    assert meta.type == 'r'
    assert meta.paradigm == 'az'
    assert meta.status == 'pending'
    assert meta.host == 'test-host'
    assert meta.git_commit == 'deadbeef'
    assert meta.cfg_checksum.startswith('sha256:')
    assert meta.timestamp.startswith('2026-05-17T14:00:00')

    out_path = schema.run_path('r013', root=tmp_path)
    assert out_path.exists()
    # Re-load to verify on-disk record validates.
    loaded = schema.load_file(out_path)
    assert loaded == meta


def test_register_custom_label_and_description(tmp_path, cfg_file):
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        label='r013_first_after_redesign',
        description='AZ Stage 3 reproducibility',
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta.label == 'r013_first_after_redesign'
    assert meta.summary.description == 'AZ Stage 3 reproducibility'


def test_register_smoke_type(tmp_path, cfg_file):
    # rename to s068 to test 's' type
    s_cfg = cfg_file.parent / 's068.toml'
    s_cfg.write_text(cfg_file.read_text(), encoding='utf-8')
    meta = register.register(
        run_id='s068',
        cfg_file=str(s_cfg),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta.type == 's'
    assert meta.run_id == 's068'


def test_register_explicit_paradigm_override(tmp_path, cfg_file_no_paradigm):
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file_no_paradigm),
        paradigm='ppo',
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta.paradigm == 'ppo'


def test_register_rejects_missing_cfg(tmp_path):
    with pytest.raises(FileNotFoundError):
        register.register(
            run_id='r013',
            cfg_file=str(tmp_path / 'nope.toml'),
            root=tmp_path,
        )


def test_register_rejects_no_paradigm(tmp_path, cfg_file_no_paradigm):
    with pytest.raises(ValueError, match='paradigm'):
        register.register(
            run_id='r013',
            cfg_file=str(cfg_file_no_paradigm),
            root=tmp_path,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )


def test_register_rejects_duplicate(tmp_path, cfg_file):
    register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    with pytest.raises(FileExistsError):
        register.register(
            run_id='r013',
            cfg_file=str(cfg_file),
            root=tmp_path,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )


def test_register_rejects_bad_run_id(tmp_path, cfg_file):
    with pytest.raises(ValueError, match='run_id'):
        register.register(
            run_id='bad-id',
            cfg_file=str(cfg_file),
            root=tmp_path,
        )


def test_register_rejects_type_run_id_contradiction(tmp_path, cfg_file):
    with pytest.raises(ValueError, match='contradicts'):
        register.register(
            run_id='r013',
            cfg_file=str(cfg_file),
            type_='s',
            root=tmp_path,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )


def test_register_rejects_label_id_contradiction(tmp_path, cfg_file):
    with pytest.raises(ValueError, match='contradicts'):
        register.register(
            run_id='r013',
            cfg_file=str(cfg_file),
            label='r014_other_slug',
            root=tmp_path,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )


def test_register_cli_main_happy(tmp_path, cfg_file, capsys):
    rc = register.main(
        [
            '--run-id',
            'r013',
            '--cfg',
            str(cfg_file),
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert 'r013' in captured.out


def test_register_cli_main_error(tmp_path, capsys):
    rc = register.main(
        [
            '--run-id',
            'r013',
            '--cfg',
            str(tmp_path / 'missing.toml'),
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 1
    captured = capsys.readouterr()
    assert 'tools.runs.register' in captured.err


def test_register_auto_injects_real_host(tmp_path, cfg_file):
    """Without explicit host=, falls back to socket.gethostname() —
    just verify it's nonempty + populated."""
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        root=tmp_path,
        now=_fixed_now(),
        git_commit='abc',
    )
    assert meta.host  # nonempty


def test_register_auto_injects_real_git_commit_or_unknown(tmp_path, cfg_file):
    """Without explicit git_commit=, falls back to subprocess git
    rev-parse HEAD or 'unknown'. Just verify nonempty string."""
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
    )
    assert meta.git_commit  # nonempty
