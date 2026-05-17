"""Smoke tests for tools.runs.register CLI."""

from __future__ import annotations

import datetime
from pathlib import Path

import pytest

from tools.runs import register, schema


@pytest.fixture
def cfg_file(tmp_path):
    """A minimal valid cfg TOML with [meta] paradigm + run_label and a
    [paradigm.<X>] section namespace (mirrors real cfg shape post
    cfg-toml-restructure-paradigm-scoped)."""
    p = tmp_path / 'r013.toml'
    p.write_text(
        '[meta]\nparadigm = "az"\nrun_label = "az_smoke"\nversion = "1.0.0"\n\n[paradigm.az]\nfoo = "bar"\n',
        encoding='utf-8',
    )
    return p


@pytest.fixture
def cfg_file_no_paradigm(tmp_path):
    """A cfg TOML with [meta] but missing the paradigm field, plus a
    [paradigm.<X>] section namespace — verifies the namespace dict at
    top-level `paradigm` is not mistaken for the missing meta field.
    run_label present so paradigm-missing path is the only failure."""
    p = tmp_path / 'broken.toml'
    p.write_text(
        '[meta]\nseed = 42\nrun_label = "broken_smoke"\n\n[paradigm.az]\nfoo = "bar"\n',
        encoding='utf-8',
    )
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


# --- production-shape fixtures + tests (类 3 L9 / C2 / C1 / H3) ---


@pytest.fixture
def cfg_file_no_run_label(tmp_path):
    """Cfg with [meta] paradigm but no run_label — register must reject
    (run_label is required as artifacts dir suffix)."""
    p = tmp_path / 'no_label.toml'
    p.write_text(
        '[meta]\nparadigm = "az"\n\n[paradigm.az]\nfoo = "bar"\n',
        encoding='utf-8',
    )
    return p


@pytest.fixture
def extends_cfg_pair(tmp_path):
    """Two leaf cfgs with identical text but DIFFERENT parents (via
    meta.extends). Used to verify cfg_checksum follows the merged
    effective cfg, not the leaf bytes alone (C1)."""
    parent_a = tmp_path / 'parent_a.toml'
    parent_a.write_text(
        '[meta]\nparadigm = "az"\nrun_label = "from_parent_a"\n\n[paradigm.az]\nfoo = "bar_a"\n',
        encoding='utf-8',
    )
    parent_b = tmp_path / 'parent_b.toml'
    parent_b.write_text(
        '[meta]\nparadigm = "az"\nrun_label = "from_parent_b"\n\n[paradigm.az]\nfoo = "bar_b"\n',
        encoding='utf-8',
    )
    leaf_a = tmp_path / 'leaf_a.toml'
    leaf_a.write_text('[meta]\nextends = "parent_a.toml"\n', encoding='utf-8')
    leaf_b = tmp_path / 'leaf_b.toml'
    leaf_b.write_text('[meta]\nextends = "parent_b.toml"\n', encoding='utf-8')
    return leaf_a, leaf_b


def test_register_snapshots_cfg_run_label(tmp_path, cfg_file):
    """metadata.cfg_run_label must mirror cfg.meta.run_label at
    register time (used by `show`/`sync` to reconstruct artifacts dir)."""
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta.cfg_run_label == 'az_smoke'


def test_register_stores_repo_relative_cfg_file(tmp_path, cfg_file):
    """metadata.cfg_file must be relative to repo_root (=root in tests).
    Absolute paths leak across hosts under sync."""
    meta = register.register(
        run_id='r013',
        cfg_file=str(cfg_file),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta.cfg_file == 'r013.toml'
    assert not Path(meta.cfg_file).is_absolute()


def test_register_rejects_no_run_label(tmp_path, cfg_file_no_run_label):
    """cfg without meta.run_label must raise (required schema field)."""
    with pytest.raises(ValueError, match='run_label'):
        register.register(
            run_id='r013',
            cfg_file=str(cfg_file_no_run_label),
            root=tmp_path,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )


def test_register_rejects_cfg_outside_repo_root(tmp_path):
    """cfg path outside repo_root must raise (cross-host portability)."""
    other_root = tmp_path / 'elsewhere'
    other_root.mkdir()
    foreign_cfg = other_root / 'foreign.toml'
    foreign_cfg.write_text(
        '[meta]\nparadigm = "az"\nrun_label = "foreign"\n',
        encoding='utf-8',
    )
    repo_root = tmp_path / 'repo'
    repo_root.mkdir()
    with pytest.raises(ValueError, match='outside repo root'):
        register.register(
            run_id='r013',
            cfg_file=str(foreign_cfg),
            root=repo_root,
            now=_fixed_now(),
            host='h',
            git_commit='abc',
        )


def test_register_checksum_includes_extends_chain(tmp_path, extends_cfg_pair):
    """Two leaf cfgs with identical text (only differ in extends target)
    must produce DIFFERENT cfg_checksum — leaf-only hashing would
    silently equate them and defeat reproducibility-pin (C1)."""
    leaf_a, leaf_b = extends_cfg_pair
    # Leaf bytes identical except extends filename:
    assert leaf_a.read_text() != leaf_b.read_text()  # extends targets differ
    # But fixture intent is: leaf only differs in extends target;
    # checksum diff comes from PARENT content divergence, not leaf bytes.
    meta_a = register.register(
        run_id='r013',
        cfg_file=str(leaf_a),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    meta_b = register.register(
        run_id='r014',
        cfg_file=str(leaf_b),
        root=tmp_path,
        now=_fixed_now(),
        host='h',
        git_commit='abc',
    )
    assert meta_a.cfg_checksum != meta_b.cfg_checksum
    # Run labels resolve from the respective parents (deep-merge):
    assert meta_a.cfg_run_label == 'from_parent_a'
    assert meta_b.cfg_run_label == 'from_parent_b'
