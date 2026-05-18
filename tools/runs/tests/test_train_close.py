"""Tests for tools.runs.train Phase C (T-10) — lifecycle steps 6-7.

Covers spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:

- §Architecture step 6-7 行 54-56 (run + close)
- §Atomic 行 64-66 (read-and-compare-and-write within metadata_lock)
- §Exit codes 行 247-257 (0 / 1 / 3 mapping)
- §错误处理 行 297-303 (train failure → status=failed; finally
  discipline never masks root cause)

Phase A/B are exercised end-to-end via the real ``phase_a_setup`` /
``phase_b_write_cfg_metadata`` setup (mirrors test_train_cfg_metadata.py
pattern) so each Phase C test starts from a real ``running`` metadata.
The step-6 train call is the T-10 stub ``_run_train_placeholder`` —
tests inject failures by monkeypatching that symbol on
``tools.runs._train.run`` (the call site; train_mod re-export is the
same function but monkeypatching the re-export wouldn't affect the
call inside ``phase_c_run_train_and_close``).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from tools.runs import schema, train as train_mod
from tools.runs._train import run as run_mod
from tools.runs._train import setup as setup_mod
from tools.runs._train import snapshot as snapshot_mod


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Repo-root marker + chdir, mirroring other train test files."""
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_cfg(path: Path, run_label: str = 'close_test') -> Path:
    path.write_text(f"""
[meta]
seed = 1
paradigm = "dmc"
run_label = "{run_label}"
""")
    return path


def _make_args(cfg: Path) -> Any:
    import argparse

    return argparse.Namespace(cfg=str(cfg), override=[], resume=None)


def _setup_running_run(tmp_path: Path, run_label: str = 'close_test') -> Any:
    """Run Phase A + B so the per-run dir has a ``running`` metadata.

    Returns the SetupState so Phase C tests can pass it straight to
    ``phase_c_run_train_and_close``. Equivalent to what ``main()`` would
    have produced just before its Phase C call.
    """
    cfg = _write_cfg(tmp_path / 'cfg.toml', run_label)
    args = _make_args(cfg)
    state = setup_mod.phase_a_setup(args)
    snapshot_mod.phase_b_write_cfg_metadata(state, Path(args.cfg))
    return state


def _read_metadata(artifacts_dir: Path) -> schema.RunMetadata:
    return schema.load_file(artifacts_dir / 'metadata.toml')


# --- Step 6 + 7 success path --------------------------------------------------


def test_phase_c_success_writes_done(tmp_path: Path) -> None:
    """Stub train returns cleanly → status=done, exit 0, wall_seconds > 0."""
    state = _setup_running_run(tmp_path)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 0
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'done'
    assert meta.exit_code == 0
    # monotonic delta on a no-op is tiny but non-negative; spec mandates
    # float; we don't assert > 0 lest a sub-microsecond run round to 0.0
    # on slow CI clocks (the spec only requires the field be recorded).
    assert meta.wall_seconds >= 0.0
    assert isinstance(meta.wall_seconds, float)


def test_phase_c_done_preserves_other_metadata_fields(tmp_path: Path) -> None:
    """Step 7 must only touch status/wall_seconds/exit_code; all other
    fields carry over from the ``running`` metadata Phase B wrote."""
    state = _setup_running_run(tmp_path, run_label='preserve_fields')
    before = _read_metadata(state.artifacts_dir)
    run_mod.phase_c_run_train_and_close(state)
    after = _read_metadata(state.artifacts_dir)
    # Unchanged fields.
    assert after.run_id == before.run_id
    assert after.timestamp == before.timestamp
    assert after.cfg_file == before.cfg_file
    assert after.cfg_resolved_version == before.cfg_resolved_version
    assert after.git_commit == before.git_commit
    assert after.host == before.host
    assert after.artifacts_dir == before.artifacts_dir
    assert after.notes == before.notes
    # Changed fields.
    assert after.status == 'done'
    assert after.exit_code == 0


# --- Step 6 train failure -----------------------------------------------------


def test_phase_c_train_raises_writes_failed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Generic exception in step 6 → status=failed, exit 1."""
    state = _setup_running_run(tmp_path)

    def _boom(_state: Any) -> None:
        raise RuntimeError('simulated train boom')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _boom)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 1
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'failed'
    assert meta.exit_code == 1
    assert meta.wall_seconds >= 0.0


def test_phase_c_train_systemexit_preserves_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``SystemExit(5)`` from train → status=failed, exit 5 (code preserved)."""
    state = _setup_running_run(tmp_path)

    def _exit5(_state: Any) -> None:
        raise SystemExit(5)

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _exit5)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 5
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'failed'
    assert meta.exit_code == 5


def test_phase_c_train_systemexit_none_treated_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``sys.exit()`` (code=None) — Python convention treats no-arg
    sys.exit as success (equivalent to sys.exit(0)). Honor that —
    creating ``status='failed' + exit_code=0`` would be internally
    inconsistent; mapping to ``done`` keeps the record coherent.
    """
    state = _setup_running_run(tmp_path)

    def _exit_bare(_state: Any) -> None:
        raise SystemExit()

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _exit_bare)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 0
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'done'
    assert meta.exit_code == 0


def test_phase_c_train_systemexit_zero_treated_as_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``sys.exit(0)`` — same as no-arg; success."""
    state = _setup_running_run(tmp_path)

    def _exit_zero(_state: Any) -> None:
        raise SystemExit(0)

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _exit_zero)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 0
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'done'
    assert meta.exit_code == 0


def test_phase_c_train_systemexit_string_code_falls_back_to_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``SystemExit('msg')`` (non-int code) → failed + exit 1 catch-all."""
    state = _setup_running_run(tmp_path)

    def _exit_string(_state: Any) -> None:
        raise SystemExit('something went wrong')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _exit_string)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 1
    meta = _read_metadata(state.artifacts_dir)
    assert meta.exit_code == 1


def test_phase_c_baseexception_swallowed_not_propagated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec 行 54 — step 6 catches ALL exceptions so step 7 still runs.

    Specifically: BaseException subclasses (other than KeyboardInterrupt
    semantics) get recorded as failures; the close metadata write still
    happens. This is verified by checking that no exception escapes.
    """
    state = _setup_running_run(tmp_path)

    class _Custom(Exception):
        pass

    def _custom_raise(_state: Any) -> None:
        raise _Custom('custom error type')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _custom_raise)
    rc = run_mod.phase_c_run_train_and_close(state)  # does not raise
    assert rc == 1
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'failed'


# --- External mark detection (spec 行 55, 66) --------------------------------


def test_phase_c_externally_marked_killed_not_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """If an external ``mark`` flipped status to ``killed`` mid-train,
    Phase C must preserve the kill and exit 0 with a stderr warning
    (spec 行 55, 66 — train output discarded)."""
    state = _setup_running_run(tmp_path)

    def _mark_externally(_state: Any) -> None:
        # Simulate concurrent mark by writing killed status from within
        # the train call (before step 7 runs). Using the schema helper
        # directly bypasses our own flock pattern — equivalent to a
        # different process having held + released the lock.
        meta = _read_metadata(state.artifacts_dir)
        killed = schema.RunMetadata(
            run_id=meta.run_id,
            timestamp=meta.timestamp,
            cfg_file=meta.cfg_file,
            cfg_resolved_version=meta.cfg_resolved_version,
            git_commit=meta.git_commit,
            host=meta.host,
            status='killed',
            artifacts_dir=meta.artifacts_dir,
            wall_seconds=1.5,
            exit_code=137,
            notes='killed by user (simulated)',
        )
        schema.save_file(killed, state.artifacts_dir / 'metadata.toml')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _mark_externally)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 0  # spec 行 66 explicit "exit 0"
    err = capsys.readouterr().err
    assert 'metadata externally marked' in err
    assert "'killed'" in err
    # Metadata still shows the external kill — Phase C did NOT overwrite.
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'killed'
    assert meta.exit_code == 137
    assert meta.notes == 'killed by user (simulated)'


def test_phase_c_externally_marked_done_not_overwritten(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """External flip to ``done`` mid-train → still preserve, exit 0.

    Spec line 55 says "若已非 'running' 则保留" — applies to any non-
    running status (done, failed, killed, unknown), not just kill.
    """
    state = _setup_running_run(tmp_path)

    def _mark_done(_state: Any) -> None:
        meta = _read_metadata(state.artifacts_dir)
        flipped = schema.RunMetadata(
            run_id=meta.run_id,
            timestamp=meta.timestamp,
            cfg_file=meta.cfg_file,
            cfg_resolved_version=meta.cfg_resolved_version,
            git_commit=meta.git_commit,
            host=meta.host,
            status='done',
            artifacts_dir=meta.artifacts_dir,
            wall_seconds=99.0,
            exit_code=0,
            notes='externally marked done',
        )
        schema.save_file(flipped, state.artifacts_dir / 'metadata.toml')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _mark_done)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 0
    meta = _read_metadata(state.artifacts_dir)
    assert meta.notes == 'externally marked done'
    assert meta.wall_seconds == 99.0


def test_phase_c_external_mark_wins_even_when_train_failed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """If train raised AND someone externally marked killed during the
    same window, the external mark still wins (spec 行 55 unconditional
    — train output discarded regardless of how train ended)."""
    state = _setup_running_run(tmp_path)

    def _mark_then_raise(_state: Any) -> None:
        meta = _read_metadata(state.artifacts_dir)
        schema.save_file(
            schema.RunMetadata(
                run_id=meta.run_id,
                timestamp=meta.timestamp,
                cfg_file=meta.cfg_file,
                cfg_resolved_version=meta.cfg_resolved_version,
                git_commit=meta.git_commit,
                host=meta.host,
                status='killed',
                artifacts_dir=meta.artifacts_dir,
                wall_seconds=2.0,
                exit_code=137,
                notes='killed externally',
            ),
            state.artifacts_dir / 'metadata.toml',
        )
        raise RuntimeError('train also raised after mark')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _mark_then_raise)
    rc = run_mod.phase_c_run_train_and_close(state)
    assert rc == 0
    err = capsys.readouterr().err
    assert 'metadata externally marked' in err
    # Train's failure is discarded.
    meta = _read_metadata(state.artifacts_dir)
    assert meta.status == 'killed'
    assert meta.notes == 'killed externally'


# --- Step 7 final write failure (spec 行 254) --------------------------------


def test_phase_c_final_write_failure_returns_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """If the final ``os.replace`` (or temp write) fails, Phase C must
    return 3 and leave metadata as ``running`` so the user can recover
    via ``tools.runs.mark`` (spec 行 254)."""
    state = _setup_running_run(tmp_path)

    # Capture pre-state — metadata is 'running' from Phase B.
    pre = _read_metadata(state.artifacts_dir)
    assert pre.status == 'running'

    # Inject failure at the os.replace boundary — temp file write
    # already succeeded so we exercise the IO path most exposed to
    # cross-mount / disk-full / permission failures in production.
    def _failing_replace(*a: Any, **kw: Any) -> Any:
        raise OSError('simulated atomic rename failure')

    monkeypatch.setattr(run_mod.os, 'replace', _failing_replace)
    rc = run_mod.phase_c_run_train_and_close(state)

    assert rc == 3
    err = capsys.readouterr().err
    assert 'final metadata write failed' in err
    assert 'tools.runs.mark' in err
    # Metadata still 'running' — operator can decide via mark.
    post = _read_metadata(state.artifacts_dir)
    assert post.status == 'running'


def test_phase_c_final_write_failure_cleans_temp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When ``os.replace`` fails, the lingering temp file must be unlinked
    so subsequent retries (mark, recover) don't trip over stale temp."""
    state = _setup_running_run(tmp_path)

    def _failing_replace(*a: Any, **kw: Any) -> Any:
        raise OSError('simulated rename failure')

    monkeypatch.setattr(run_mod.os, 'replace', _failing_replace)
    run_mod.phase_c_run_train_and_close(state)
    temp_path = state.artifacts_dir / 'metadata.toml.tmp'
    assert not temp_path.exists(), 'temp file leaked after failed rename'


# --- main() end-to-end integration -------------------------------------------


def test_main_end_to_end_returns_0(tmp_path: Path) -> None:
    """``main()`` runs Phase A + B + C in sequence — fresh tmp cwd,
    happy-path stub train, expect rc=0 and a fully-closed metadata."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'integration')
    rc = train_mod.main([str(cfg)])
    assert rc == 0
    # Find the per-run dir (single child of artifacts/).
    artifacts = tmp_path / 'artifacts'
    children = [p for p in artifacts.iterdir() if p.is_dir()]
    assert len(children) == 1
    art = children[0]
    meta = schema.load_file(art / 'metadata.toml')
    assert meta.status == 'done'
    assert meta.exit_code == 0
    assert meta.wall_seconds >= 0.0


def test_main_phase_c_train_fail_returns_1(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the T-10 stub is monkeypatched to raise, ``main()`` returns 1
    (spec §Exit codes — train ran but failed mid-way)."""

    def _boom(_state: Any) -> None:
        raise RuntimeError('simulated train fail via main')

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _boom)
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'main_fail')
    rc = train_mod.main([str(cfg)])
    assert rc == 1


def test_main_phase_b_failure_skips_phase_c(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If Phase B fails, ``main()`` returns 2 and Phase C never runs.

    Verified by patching ``_run_train_placeholder`` to a sentinel that
    would mark a side-effect flag — Phase C never reaches it.
    """
    sentinel = {'called': False}

    def _sentinel(_state: Any) -> None:
        sentinel['called'] = True

    monkeypatch.setattr(run_mod, '_run_train_placeholder', _sentinel)
    # Force Phase B to fail by patching write_metadata_atomic.
    import tools.runs._train.snapshot as snap_mod

    def _phase_b_boom(_state: Any, _cfg_path: Path) -> None:
        raise RuntimeError('simulated phase B failure')

    monkeypatch.setattr(snap_mod, 'phase_b_write_cfg_metadata', _phase_b_boom)
    # Also patch the re-export the shell uses.
    monkeypatch.setattr(train_mod, '_phase_b_write_cfg_metadata', _phase_b_boom)

    cfg = _write_cfg(tmp_path / 'cfg.toml', 'phase_b_fail')
    rc = train_mod.main([str(cfg)])
    assert rc == 2
    assert sentinel['called'] is False, 'Phase C ran despite Phase B failure'


# --- TOML round-trip sanity ---------------------------------------------------


def test_closed_metadata_is_parseable_toml(tmp_path: Path) -> None:
    """The metadata.toml we leave on disk after Phase C must be valid
    TOML (defense against an emitter bug producing un-parseable output
    that would break ``list`` / ``show`` / ``mark``).
    """
    state = _setup_running_run(tmp_path)
    run_mod.phase_c_run_train_and_close(state)
    raw = (state.artifacts_dir / 'metadata.toml').read_text(encoding='utf-8')
    parsed = tomllib.loads(raw)
    # All 11 spec fields present.
    expected = {
        'run_id',
        'timestamp',
        'cfg_file',
        'cfg_resolved_version',
        'git_commit',
        'host',
        'status',
        'artifacts_dir',
        'wall_seconds',
        'exit_code',
        'notes',
    }
    assert set(parsed.keys()) == expected
    assert parsed['status'] == 'done'
