"""T-12 resume — basic flow + validation + status + preserved + wall_seconds.

Spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:

- §Resume 语义 行 145-164 (full lifecycle)
- §Resume 例外规则 CRIT-2-A 行 235-246 (status transitions)
- HIGH-2-C 行 149 (leaf cfg required)
- H-3 行 185 (wall_seconds overwrite = last attempt)
- 行 162 preserved metadata fields (timestamp, exit_code)

Companion file ``test_train_resume_versioning.py`` covers:
cfg_resolved_v<N> allocation, parallel resume serialization,
override application, SetupState shape, Phase B skip-metadata-write,
versioned-filename helper.

Shared fixtures + helpers live in ``_resume_fixtures.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tools.runs import schema, train as train_mod
from tools.runs._train import resume as resume_mod
from tools.runs.tests._resume_fixtures import (
    fresh_train,
    isolate_cwd,  # noqa: F401 — autouse via parametrize below
    make_args,
    make_dummy_ckpt,
    stub_train,  # noqa: F401 — autouse via parametrize below
    write_cfg,
)


# Use the shared fixtures as autouse here. (Importing the fixture
# function then re-declaring an ``autouse=True`` wrapper is the
# canonical pytest pattern for sharing fixtures across files.)


@pytest.fixture(autouse=True)
def _isolate_cwd(isolate_cwd: Path) -> Path:  # noqa: F811
    return isolate_cwd


@pytest.fixture(autouse=True)
def _stub_train(stub_train: None) -> None:  # noqa: F811
    pass


# --- Resume basic flow --------------------------------------------------------


def test_resume_reuses_artifacts_dir(tmp_path: Path) -> None:
    """Resume must NOT mkdir a new artifacts_dir — it reuses the existing
    one. metadata.run_id stays constant; the per-run dir count stays at 1.
    """
    cfg, art = fresh_train(tmp_path)
    pre_run_id = schema.load_file(art / 'metadata.toml').run_id
    ckpt = make_dummy_ckpt(art)

    rc = train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert rc == 0

    children = [p for p in (tmp_path / 'artifacts').iterdir() if p.is_dir()]
    assert len(children) == 1
    assert children[0] == art
    post_run_id = schema.load_file(art / 'metadata.toml').run_id
    assert post_run_id == pre_run_id


def test_resume_writes_paired_v2_files(tmp_path: Path) -> None:
    """Spec 行 156 pair-versioning: both cfg_leaf_v2.toml and
    cfg_resolved_v2.toml appear; v1 (unsuffixed) files remain."""
    cfg, art = fresh_train(tmp_path)
    assert (art / 'cfg_leaf.toml').exists()
    assert (art / 'cfg_resolved.toml').exists()
    ckpt = make_dummy_ckpt(art)

    train_mod.main([str(cfg), '--resume', str(ckpt)])

    assert (art / 'cfg_leaf.toml').exists()
    assert (art / 'cfg_resolved.toml').exists()
    assert (art / 'cfg_leaf_v2.toml').exists()
    assert (art / 'cfg_resolved_v2.toml').exists()


def test_resume_bumps_cfg_resolved_version_metadata_field(tmp_path: Path) -> None:
    """Spec 行 158 CRIT-6-A: metadata.cfg_resolved_version reflects current truth."""
    cfg, art = fresh_train(tmp_path)
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 1
    ckpt = make_dummy_ckpt(art)

    train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 2


# --- Resume validation guards (HIGH-2-C + sanity) ----------------------------


def test_resume_missing_cfg_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Spec 行 149 HIGH-2-C: leaf cfg must exist + be readable."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    missing = tmp_path / 'gone.toml'
    assert not missing.exists()

    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(missing), '--resume', str(ckpt)])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert 'leaf cfg 缺失' in err


def test_resume_metadata_missing_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Spec 行 150: <artifacts_dir>/metadata.toml must exist."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    (art / 'metadata.toml').unlink()

    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert 'resume needs registered run' in err


def test_resume_ckpt_parent_not_ckpts_subdir_exits_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Spec 行 150: ckpt parent must be the ``ckpts/`` subdir."""
    cfg, art = fresh_train(tmp_path)
    flat_ckpt = art / 'rogue_ckpt.pt'
    flat_ckpt.write_bytes(b'no subdir')

    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(cfg), '--resume', str(flat_ckpt)])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert 'resume needs registered run' in err


def test_resume_cfg_pointing_to_dir_exits_2(tmp_path: Path) -> None:
    """cfg path must be a file, not a dir."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    not_a_file = tmp_path / 'some_dir'
    not_a_file.mkdir()

    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(not_a_file), '--resume', str(ckpt)])
    assert ei.value.code == 2


def test_resume_load_with_extends_fail_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Spec 行 152: resume re-resolves cfg; if load_with_extends raises
    (malformed TOML / missing extends parent), exit 2 with stderr
    diagnostic. Covers resume.py 行 142-144 raise path (I-1 — was
    untested before the v1 quality review).

    Strategy: fresh_train captures the artifacts dir + ckpt; then we
    overwrite the leaf cfg with malformed TOML (unterminated string)
    and re-invoke main() in --resume mode. The leaf-bytes parse
    actually happens in :func:`_extract_leaf_label` before we reach
    ``load_with_extends`` — that earlier guard raises SystemExit(2)
    too, but with a different stderr token. To exercise specifically
    the ``load_with_extends`` path (which parses on disk via tomllib +
    walks the ``extends`` chain), we point ``extends`` at a missing
    parent file: leaf-bytes TOML is valid (passes _extract_leaf_label)
    but extends resolution fails.
    """
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)

    # Valid TOML so _extract_leaf_label succeeds; broken meta.extends
    # so load_with_extends raises FileNotFoundError (resume.py 行 142
    # catches both ValueError and FileNotFoundError).
    cfg.write_text(
        """
[meta]
seed = 1
paradigm = "dmc"
run_label = "resume_test"
extends = "missing_parent.toml"
"""
    )

    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert 'cfg resolve failed' in err


def test_resume_override_apply_fail_exit_2(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Spec 行 152: --override is applied during resume; malformed
    override (e.g. missing ``=``) → exit 2 with stderr diagnostic.
    Covers resume.py 行 148-150 raise path (I-1 — was untested before
    the v1 quality review).
    """
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)

    with pytest.raises(SystemExit) as ei:
        train_mod.main(
            [str(cfg), '--resume', str(ckpt), '--override', 'bad-no-equals'],
        )
    assert ei.value.code == 2
    err = capsys.readouterr().err
    assert '--override apply failed' in err


# --- Status transitions (CRIT-2-A) -------------------------------------------


@pytest.mark.parametrize('prior_status', ['done', 'failed', 'killed', 'unknown'])
def test_resume_transitions_non_running_to_running(tmp_path: Path, prior_status: str) -> None:
    """Spec 行 238 CRIT-2-A: {done,failed,killed,unknown} → running allowed
    only on resume code path. Each prior status round-trips through
    resume Phase A to running.
    """
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    meta = schema.load_file(art / 'metadata.toml')
    flipped = schema.RunMetadata(
        run_id=meta.run_id,
        timestamp=meta.timestamp,
        cfg_file=meta.cfg_file,
        cfg_resolved_version=meta.cfg_resolved_version,
        git_commit=meta.git_commit,
        host=meta.host,
        status=prior_status,
        artifacts_dir=meta.artifacts_dir,
        wall_seconds=meta.wall_seconds,
        exit_code=meta.exit_code,
        notes=meta.notes,
    )
    schema.save_file(flipped, art / 'metadata.toml')
    assert schema.load_file(art / 'metadata.toml').status == prior_status

    rc = train_mod.main([str(cfg), '--resume', str(ckpt)])
    # Phase C close transitions running → done (stub train succeeds).
    assert rc == 0
    final = schema.load_file(art / 'metadata.toml').status
    assert final == 'done'


def test_resume_running_already_warns_and_proceeds(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Spec 行 243: status='running' already → warn + no-op + continue."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    meta = schema.load_file(art / 'metadata.toml')
    running = schema.RunMetadata(
        run_id=meta.run_id,
        timestamp=meta.timestamp,
        cfg_file=meta.cfg_file,
        cfg_resolved_version=meta.cfg_resolved_version,
        git_commit=meta.git_commit,
        host=meta.host,
        status='running',
        artifacts_dir=meta.artifacts_dir,
        wall_seconds=0.0,
        exit_code=0,
        notes=meta.notes,
    )
    schema.save_file(running, art / 'metadata.toml')

    rc = train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert rc == 0
    err = capsys.readouterr().err
    assert 'metadata already running' in err
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 2


# --- Preserved metadata fields (spec 行 162) ---------------------------------


def test_resume_preserves_timestamp(tmp_path: Path) -> None:
    """spec 行 162: timestamp held at first train start; resume does NOT reset."""
    cfg, art = fresh_train(tmp_path)
    pre_ts = schema.load_file(art / 'metadata.toml').timestamp
    ckpt = make_dummy_ckpt(art)

    train_mod.main([str(cfg), '--resume', str(ckpt)])
    post_ts = schema.load_file(art / 'metadata.toml').timestamp
    assert post_ts == pre_ts


def test_resume_preserves_exit_code_through_phase_a(tmp_path: Path) -> None:
    """spec 行 162: exit_code preserved by Phase A bump; Phase C close
    overwrites with the new attempt's outcome. Here we verify Phase A
    in isolation (before Phase C runs) preserves the prior exit_code.
    """
    cfg, art = fresh_train(tmp_path)
    meta = schema.load_file(art / 'metadata.toml')
    failed = schema.RunMetadata(
        run_id=meta.run_id,
        timestamp=meta.timestamp,
        cfg_file=meta.cfg_file,
        cfg_resolved_version=meta.cfg_resolved_version,
        git_commit=meta.git_commit,
        host=meta.host,
        status='failed',
        artifacts_dir=meta.artifacts_dir,
        wall_seconds=12.5,
        exit_code=7,
        notes='prior failed attempt',
    )
    schema.save_file(failed, art / 'metadata.toml')
    ckpt = make_dummy_ckpt(art)

    args = make_args(cfg, resume=str(ckpt))
    state = resume_mod.phase_a_resume(args)
    intermediate = schema.load_file(art / 'metadata.toml')
    assert intermediate.exit_code == 7
    assert intermediate.status == 'running'
    assert intermediate.cfg_resolved_version == 2
    assert state.cfg_resolved_version == 2
    assert state.resume_ckpt_path == ckpt


def test_resume_updates_cfg_file_to_new_leaf_path(tmp_path: Path) -> None:
    """spec 行 159: cfg_file records "last leaf path used"."""
    cfg, art = fresh_train(tmp_path)
    pre_cfg = schema.load_file(art / 'metadata.toml').cfg_file
    assert pre_cfg == 'cfg.toml'
    ckpt = make_dummy_ckpt(art)
    other_cfg = tmp_path / 'other.toml'
    write_cfg(other_cfg, 'resume_test')  # same run_label to satisfy regex

    train_mod.main([str(other_cfg), '--resume', str(ckpt)])
    post_cfg = schema.load_file(art / 'metadata.toml').cfg_file
    assert post_cfg == 'other.toml'


# --- wall_seconds overwrite (H-3 行 185) -------------------------------------


def test_resume_wall_seconds_overwritten_at_close(tmp_path: Path) -> None:
    """spec 行 185 H-3: wall_seconds == last-attempt elapsed (overwrite,
    not accumulate). Inject a non-zero wall_seconds in prior metadata +
    check that Phase C close overwrites with the new attempt's duration.
    """
    cfg, art = fresh_train(tmp_path)
    meta = schema.load_file(art / 'metadata.toml')
    pretend = schema.RunMetadata(
        run_id=meta.run_id,
        timestamp=meta.timestamp,
        cfg_file=meta.cfg_file,
        cfg_resolved_version=meta.cfg_resolved_version,
        git_commit=meta.git_commit,
        host=meta.host,
        status='failed',
        artifacts_dir=meta.artifacts_dir,
        wall_seconds=999.0,
        exit_code=1,
        notes='',
    )
    schema.save_file(pretend, art / 'metadata.toml')
    ckpt = make_dummy_ckpt(art)

    rc = train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert rc == 0
    final = schema.load_file(art / 'metadata.toml')
    assert final.wall_seconds < 60.0
    assert final.wall_seconds != 999.0
    assert final.exit_code == 0
    assert final.status == 'done'
