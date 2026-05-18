"""T-12 resume — cfg_resolved_v<N> allocation + parallel + Phase B specifics.

Spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:

- CRIT-6-A 行 157-160 (cfg_resolved_v<N> truth + metadata field)
- HIGH-3-A 行 155 (allocator-lock-guarded N allocation)
- 行 156    pair-versioning (cfg_leaf_v<N>.toml ↔ cfg_resolved_v<N>.toml)
- 行 152    override allowed during resume

Companion file ``test_train_resume.py`` covers basic flow + validation +
status + preserved fields + wall_seconds.

Shared fixtures + helpers live in ``_resume_fixtures.py``.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any

import pytest

from tools.runs import schema, train as train_mod
from tools.runs._train import resume as resume_mod
from tools.runs._train import setup as setup_mod
from tools.runs._train import snapshot as snapshot_mod
from tools.runs.tests._resume_fixtures import (
    fresh_train,
    isolate_cwd,  # noqa: F401 — re-exported via wrapper below
    make_args,
    make_dummy_ckpt,
    stub_train,  # noqa: F401 — re-exported via wrapper below
    write_cfg,
)


@pytest.fixture(autouse=True)
def _isolate_cwd(isolate_cwd: Path) -> Path:  # noqa: F811
    return isolate_cwd


@pytest.fixture(autouse=True)
def _stub_train(stub_train: None) -> None:  # noqa: F811
    pass


# --- cfg_resolved_v<N> N allocation algorithm --------------------------------


def test_next_cfg_resolved_version_with_only_v1(tmp_path: Path) -> None:
    """Only cfg_resolved.toml present → next = 2."""
    art = tmp_path / 'somedir'
    art.mkdir()
    (art / 'cfg_resolved.toml').write_text('[meta]\n')
    assert resume_mod._next_cfg_resolved_version(art) == 2


def test_next_cfg_resolved_version_with_v2(tmp_path: Path) -> None:
    """v1 + v2 present → next = 3."""
    art = tmp_path / 'somedir'
    art.mkdir()
    (art / 'cfg_resolved.toml').write_text('[meta]\n')
    (art / 'cfg_resolved_v2.toml').write_text('[meta]\n')
    assert resume_mod._next_cfg_resolved_version(art) == 3


def test_next_cfg_resolved_version_skips_stale_backups(tmp_path: Path) -> None:
    """Defensive: non-matching files (e.g. cfg_resolved.toml.bak) don't
    bump the version. Only canonical ``cfg_resolved_v<N>.toml`` counts.
    """
    art = tmp_path / 'somedir'
    art.mkdir()
    (art / 'cfg_resolved.toml').write_text('[meta]\n')
    (art / 'cfg_resolved.toml.bak').write_text('[meta]\n')
    (art / 'cfg_resolved_vXYZ.toml').write_text('[meta]\n')  # non-numeric
    (art / 'cfg_resolved_v3.toml').write_text('[meta]\n')
    assert resume_mod._next_cfg_resolved_version(art) == 4


def test_next_cfg_resolved_version_picks_max_not_count(tmp_path: Path) -> None:
    """Algorithm is max+1, not count+1 — even if v2 is missing, v3
    present → next = 4."""
    art = tmp_path / 'somedir'
    art.mkdir()
    (art / 'cfg_resolved.toml').write_text('[meta]\n')
    (art / 'cfg_resolved_v5.toml').write_text('[meta]\n')
    assert resume_mod._next_cfg_resolved_version(art) == 6


def test_resume_three_times_climbs_to_v4(tmp_path: Path) -> None:
    """fresh (v1) → resume (v2) → resume (v3) → resume (v4). Each
    resume's metadata reflects the new max."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)

    train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 2
    assert (art / 'cfg_resolved_v2.toml').exists()

    train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 3
    assert (art / 'cfg_resolved_v3.toml').exists()

    train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 4
    assert (art / 'cfg_resolved_v4.toml').exists()


# --- Allocator-lock serialization (HIGH-3-A) ---------------------------------


def test_parallel_resumes_get_distinct_versions(tmp_path: Path) -> None:
    """spec 行 155 HIGH-3-A: two parallel resumes against the same dir
    must get distinct ``cfg_resolved_version`` values (no collision).

    Two threads enter ``phase_a_resume`` simultaneously via a Barrier;
    each runs Phase A+B (Phase A allocates the version under the
    allocator flock + writes metadata; Phase B writes the
    ``cfg_resolved_v<N>.toml``). Distinct N invariant: the set of
    observed versions has cardinality == call count.

    The per-thread fd flock semantics differ by platform (Linux: per-fd
    fcntl; macOS: per-process BSD). The metadata read-modify-write
    inside the allocator critical section is what serializes the
    version bump in either case.
    """
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)

    errors: list[BaseException] = []
    versions_seen: list[int] = []
    versions_lock = threading.Lock()
    barrier = threading.Barrier(2)

    def _do_resume() -> None:
        try:
            barrier.wait()
            args = make_args(cfg, resume=str(ckpt))
            state = resume_mod.phase_a_resume(args)
            snapshot_mod.phase_b_write_cfg_metadata(state, Path(args.cfg))
            with versions_lock:
                versions_seen.append(state.cfg_resolved_version)
        except BaseException as e:
            errors.append(e)

    t1 = threading.Thread(target=_do_resume)
    t2 = threading.Thread(target=_do_resume)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    if len(errors) == 2:
        pytest.fail(f'both resumes raised: {errors}')

    assert len(set(versions_seen)) == len(versions_seen), f'cfg_resolved_version collision: {versions_seen}'

    vN_files = sorted(p.name for p in art.iterdir() if p.name.startswith('cfg_resolved_v'))
    for v in versions_seen:
        assert f'cfg_resolved_v{v}.toml' in vN_files, f'allocated v{v} but file not on disk; vN_files={vN_files}'
    final_version = schema.load_file(art / 'metadata.toml').cfg_resolved_version
    assert final_version == max(versions_seen)


# --- Override application during resume --------------------------------------


def test_resume_applies_override(tmp_path: Path) -> None:
    """spec 行 152: resume re-resolves cfg + applies --override (allow drift)."""
    cfg = write_cfg(
        tmp_path / 'cfg.toml',
        'resume_test',
        extra='[paradigm.dmc]\nbatch_size = 16',
    )
    train_mod.main([str(cfg)])
    art = next(p for p in (tmp_path / 'artifacts').iterdir() if p.is_dir())
    ckpt = make_dummy_ckpt(art)

    train_mod.main(
        [str(cfg), '--resume', str(ckpt), '--override', 'paradigm.dmc.batch_size=64'],
    )

    import tomllib

    resolved_v2 = tomllib.loads((art / 'cfg_resolved_v2.toml').read_text(encoding='utf-8'))
    assert resolved_v2['paradigm']['dmc']['batch_size'] == 64


# --- SetupState shape -------------------------------------------------------


def test_setup_state_resume_ckpt_path_populated_on_resume(tmp_path: Path) -> None:
    """SetupState carries the resume_ckpt_path to Phase C dispatch."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    args = make_args(cfg, resume=str(ckpt))
    state = resume_mod.phase_a_resume(args)
    assert state.resume_ckpt_path == ckpt
    assert state.cfg_resolved_version == 2
    assert state.artifacts_dir == art


def test_setup_state_resume_ckpt_path_none_on_fresh(tmp_path: Path) -> None:
    cfg = write_cfg(tmp_path / 'cfg.toml', 'fresh_check')
    args = make_args(cfg, resume=None)
    state = setup_mod.phase_a_setup(args)
    assert state.resume_ckpt_path is None
    assert state.cfg_resolved_version == 1


# --- Phase B skip metadata write on resume -----------------------------------


def test_phase_b_on_resume_does_not_rewrite_metadata(tmp_path: Path) -> None:
    """Phase A resume already wrote metadata (under allocator lock).
    Phase B on resume must NOT call write_metadata_atomic again — that
    would either duplicate work or accidentally reset Phase A's
    preserved fields. Verify by counting write_metadata_atomic calls.
    """
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    args = make_args(cfg, resume=str(ckpt))
    state = resume_mod.phase_a_resume(args)

    calls: list[Any] = []

    def _count_write(*a: Any, **kw: Any) -> None:
        calls.append((a, kw))

    import tools.runs._train.snapshot as snap

    original = snap.write_metadata_atomic
    snap.write_metadata_atomic = _count_write  # type: ignore[assignment]
    try:
        snapshot_mod.phase_b_write_cfg_metadata(state, Path(args.cfg))
    finally:
        snap.write_metadata_atomic = original  # type: ignore[assignment]

    assert calls == [], 'Phase B called write_metadata_atomic on resume path'


# --- Phase B failure on resume: no rmtree of registered dir ------------------


def test_phase_b_failure_on_resume_does_not_rmtree(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A Phase B failure on the resume path must NOT rmtree the
    artifacts_dir — it holds prior ckpts, older cfg versions, the
    just-bumped metadata. The fresh-path rmtree convention does not
    apply (the dir is not "orphan"; it's a registered run).
    """
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    args = make_args(cfg, resume=str(ckpt))
    state = resume_mod.phase_a_resume(args)
    assert schema.load_file(art / 'metadata.toml').cfg_resolved_version == 2

    real_write_text = Path.write_text

    def patched_write_text(self: Path, *a: Any, **kw: Any) -> int:  # noqa: ANN401
        if self.name == 'cfg_resolved_v2.toml':
            raise OSError('simulated disk full on resume Phase B')
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, 'write_text', patched_write_text)

    with pytest.raises(SystemExit) as ei:
        snapshot_mod.phase_b_write_cfg_metadata(state, Path(args.cfg))
    assert ei.value.code == 2

    assert art.exists(), 'resume Phase B failure incorrectly rmtree-d the registered dir'
    assert (art / 'ckpts' / 'ckpt_30.pt').exists()
    assert (art / 'metadata.toml').exists()
    assert (art / 'cfg_resolved.toml').exists()
    assert (art / 'cfg_leaf.toml').exists()


# --- Versioned filename helper ----------------------------------------------


def test_versioned_filenames_v1_unsuffixed() -> None:
    assert snapshot_mod._versioned_filenames(1) == ('cfg_leaf.toml', 'cfg_resolved.toml')


def test_versioned_filenames_v2_suffixed() -> None:
    assert snapshot_mod._versioned_filenames(2) == (
        'cfg_leaf_v2.toml',
        'cfg_resolved_v2.toml',
    )


def test_versioned_filenames_high_n() -> None:
    assert snapshot_mod._versioned_filenames(42) == (
        'cfg_leaf_v42.toml',
        'cfg_resolved_v42.toml',
    )


def test_versioned_filenames_rejects_zero() -> None:
    with pytest.raises(ValueError, match='must be >= 1'):
        snapshot_mod._versioned_filenames(0)


def test_versioned_filenames_rejects_negative() -> None:
    with pytest.raises(ValueError, match='must be >= 1'):
        snapshot_mod._versioned_filenames(-5)
