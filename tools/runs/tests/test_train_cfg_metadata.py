"""Tests for tools.runs.train Phase B (T-09) — lifecycle steps 4-5.

Covers spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:

- §Architecture step 4-5 行 50-53
- §Per-run dir 行 76-96 (cfg_leaf / cfg_resolved / metadata layout)
- §Per-run dir 行 82 (cfg_leaf == cfg_resolved 内容相同 when no extends, both written)
- HIGH-2-B 行 51, 53 orphan-dir rmtree on Phase B failure
- 行 174-189 Schema metadata.toml 11 fields
- 行 279-292 metadata atomic rename

Phase A (T-08) is exercised end-to-end via the real ``phase_a_setup``
fixture builder so Phase B test setup mirrors production lifecycle —
no SetupState mock-construction (the dataclass shape is frozen by
Phase A's regression suite; duplicating it here would just drift).
"""

from __future__ import annotations

import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib  # type: ignore

from tools.runs import schema, train as train_mod
from tools.runs._train import setup as setup_mod
from tools.runs._train import snapshot as snapshot_mod


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Mirror test_train_setup.py — each test gets a fresh tmp cwd with a
    ``tools/runs/`` marker so ``_verify_repo_root`` accepts it."""
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_cfg(path: Path, run_label: str, *, extra: str = '', paradigm: str = 'dmc') -> Path:
    body = f"""
[meta]
seed = 1
paradigm = "{paradigm}"
run_label = "{run_label}"
"""
    if extra:
        body += '\n' + extra + '\n'
    path.write_text(body)
    return path


def _make_args(cfg: Path, **kw: Any) -> Any:
    import argparse

    return argparse.Namespace(
        cfg=str(cfg),
        override=list(kw.get('override', [])),
        resume=kw.get('resume'),
    )


def _run_phase_a_then_b(cfg: Path, **kw: Any) -> tuple[Any, Path]:
    """Run Phase A + Phase B in sequence (mirrors main() integration)."""
    args = _make_args(cfg, **kw)
    state = setup_mod.phase_a_setup(args)
    snapshot_mod.phase_b_write_cfg_metadata(state, Path(args.cfg))
    return state, state.artifacts_dir


# --- Step 4a: cfg_leaf.toml write ---------------------------------------------


def test_cfg_leaf_written_bytes_round_trip(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'leaf_bytes')
    original_bytes = cfg.read_bytes()
    state, art = _run_phase_a_then_b(cfg)
    leaf = art / 'cfg_leaf.toml'
    assert leaf.exists()
    # Pure byte-for-byte snapshot — no re-encoding through TOML emitter.
    assert leaf.read_bytes() == original_bytes
    assert leaf.read_bytes() == state.cfg_leaf_bytes


def test_cfg_leaf_immune_to_post_phase_b_cfg_edit(tmp_path: Path) -> None:
    """Editing the source cfg after Phase B must not retroactively
    change the snapshot — confirms write_bytes happened immediately."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'edit_test')
    _state, art = _run_phase_a_then_b(cfg)
    leaf_before = (art / 'cfg_leaf.toml').read_bytes()
    cfg.write_text('# mutated\n[meta]\nrun_label = "x"\n')
    assert (art / 'cfg_leaf.toml').read_bytes() == leaf_before


# --- Step 4b: cfg_resolved.toml write -----------------------------------------


def test_cfg_resolved_parses_back_to_resolved_dict(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'resolved_rt', extra='[paradigm.dmc]\nbatch_size = 32')
    state, art = _run_phase_a_then_b(cfg)
    resolved = art / 'cfg_resolved.toml'
    assert resolved.exists()
    reparsed = tomllib.loads(resolved.read_text(encoding='utf-8'))
    assert reparsed == state.cfg_resolved


def test_cfg_leaf_equals_cfg_resolved_when_no_extends(tmp_path: Path) -> None:
    """spec 行 82 — cfg without extends still gets both files (structural
    symmetry); content must round-trip to the same parsed dict."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'no_extends')
    _state, art = _run_phase_a_then_b(cfg)
    leaf_dict = tomllib.loads((art / 'cfg_leaf.toml').read_text(encoding='utf-8'))
    resolved_dict = tomllib.loads((art / 'cfg_resolved.toml').read_text(encoding='utf-8'))
    assert leaf_dict == resolved_dict


def test_cfg_resolved_differs_from_leaf_when_extends_present(tmp_path: Path) -> None:
    parent = tmp_path / 'parent.toml'
    parent.write_text("""
[meta]
seed = 7
paradigm = "dmc"
run_label = "parent_lbl"

[pipeline]
mode = "serial"
""")
    child = tmp_path / 'child.toml'
    child.write_text("""
[meta]
extends = "parent.toml"
run_label = "child_lbl"
""")
    _state, art = _run_phase_a_then_b(child)
    leaf_dict = tomllib.loads((art / 'cfg_leaf.toml').read_text(encoding='utf-8'))
    resolved_dict = tomllib.loads((art / 'cfg_resolved.toml').read_text(encoding='utf-8'))
    # Leaf reads only child's literal text — has extends ref.
    assert leaf_dict['meta'].get('extends') == 'parent.toml'
    # Resolved has parent + child merged (and extends stripped after merge).
    assert resolved_dict['meta']['seed'] == 7
    assert resolved_dict['meta']['run_label'] == 'child_lbl'
    assert resolved_dict['pipeline']['mode'] == 'serial'
    assert 'extends' not in resolved_dict['meta']
    assert leaf_dict != resolved_dict


def test_cfg_resolved_with_override_reflects_override(tmp_path: Path) -> None:
    cfg = _write_cfg(
        tmp_path / 'cfg.toml',
        'override_test',
        extra='[paradigm.dmc]\nbatch_size = 16',
    )
    state, art = _run_phase_a_then_b(cfg, override=['paradigm.dmc.batch_size=64'])
    resolved_dict = tomllib.loads((art / 'cfg_resolved.toml').read_text(encoding='utf-8'))
    assert resolved_dict['paradigm']['dmc']['batch_size'] == 64
    assert resolved_dict == state.cfg_resolved


def test_cfg_resolved_handles_real_cfg_shape(tmp_path: Path) -> None:
    """Real cfg shapes — inline table, list, bools, floats, escaped string —
    all round-trip through the Phase B emitter back to the source dict.
    Type-level emitter edge cases live in test_train_cfg_toml.py."""
    cfg = _write_cfg(
        tmp_path / 'cfg.toml',
        'real_shape',
        extra="""
[scenario]
team_0 = ["A", "B"]
deck_padding = { card = "x", target_size = 15 }
pool = ["v_legacy", "test_basic"]
note = "He said \\"hi\\" \\\\ done"

[paradigm.dmc]
lr = 0.0001
use_amp = true
no_clip = false
""",
    )
    state, art = _run_phase_a_then_b(cfg)
    resolved_dict = tomllib.loads((art / 'cfg_resolved.toml').read_text(encoding='utf-8'))
    assert resolved_dict == state.cfg_resolved


# --- Step 5: metadata.toml write ----------------------------------------------


def test_metadata_written_with_status_running(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'meta_running')
    _state, art = _run_phase_a_then_b(cfg)
    meta_path = art / 'metadata.toml'
    assert meta_path.exists()
    meta = schema.load_file(meta_path)
    assert meta.status == 'running'


def test_metadata_has_all_eleven_fields(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'meta_fields')
    _state, art = _run_phase_a_then_b(cfg)
    raw = tomllib.loads((art / 'metadata.toml').read_text(encoding='utf-8'))
    assert set(raw.keys()) == {
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


def test_metadata_run_id_six_digit_zero_padded(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'pad_test')
    state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    assert meta.run_id == f'{state.nnn:06d}'
    assert len(meta.run_id) == 6
    assert meta.run_id.isdigit()


def test_metadata_timestamp_matches_state_timestamp_utc(tmp_path: Path) -> None:
    """Spec 行 70 / 行 178 — metadata.timestamp 与 dir-name ts 同源
    (state.timestamp_utc)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'ts_check')
    state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    assert meta.timestamp == state.timestamp_utc.isoformat()
    # iso8601 round-trip yields the same datetime back.
    assert datetime.fromisoformat(meta.timestamp) == state.timestamp_utc


def test_metadata_cfg_resolved_version_is_one(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'v1_check')
    _state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    # spec 行 180 — 首版 = 1, resume 递增 (T-12 territory).
    assert meta.cfg_resolved_version == 1


def test_metadata_git_commit_real_or_unknown(tmp_path: Path) -> None:
    """git_commit either is a real SHA (test env's repo HEAD) or
    'unknown' fallback. Both are valid per spec §Schema."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'git_check')
    _state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    if meta.git_commit != 'unknown':
        assert len(meta.git_commit) >= 7
        assert all(c in '0123456789abcdef' for c in meta.git_commit.lower())


class _GitFailResult:
    returncode = 128
    stdout = ''
    stderr = 'fatal: not a git repository'


@pytest.mark.parametrize(
    'fake_run',
    [
        pytest.param(
            lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError('git not installed')),
            id='git_missing',
        ),
        pytest.param(lambda *a, **kw: _GitFailResult(), id='git_returns_nonzero'),
        pytest.param(
            lambda *a, **kw: (_ for _ in ()).throw(subprocess.TimeoutExpired(cmd=a, timeout=5)),
            id='git_timeout',
        ),
    ],
)
def test_metadata_git_commit_falls_back_to_unknown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, fake_run: Any
) -> None:
    """All three git-unavailable paths (missing binary / nonzero rc /
    timeout) must collapse to 'unknown' fallback per spec §Schema."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'git_fallback')
    monkeypatch.setattr(snapshot_mod.subprocess, 'run', fake_run)
    _state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    assert meta.git_commit == 'unknown'


def test_metadata_host_is_socket_hostname(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'host_check')
    _state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    assert meta.host == socket.gethostname()


def test_metadata_artifacts_dir_is_repo_relative_posix(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'dir_check')
    state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    # Must be repo-relative (starts with 'artifacts/') and use forward slashes.
    assert meta.artifacts_dir.startswith('artifacts/')
    assert '\\' not in meta.artifacts_dir
    # Resolves back to the actual dir.
    assert (tmp_path / meta.artifacts_dir).resolve() == state.artifacts_dir.resolve()


def test_metadata_cfg_file_is_repo_relative_posix(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'cfg_path_check')
    _state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    # cfg_file records the user-passed leaf cfg path (spec 行 179).
    assert meta.cfg_file == 'cfg.toml'
    assert '\\' not in meta.cfg_file


def test_metadata_running_state_placeholders(tmp_path: Path) -> None:
    """wall_seconds=0.0 / exit_code=0 / notes='' are running-state
    placeholders (spec 行 185 + Phase C T-10 overwrite responsibility)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'placeholders')
    _state, art = _run_phase_a_then_b(cfg)
    meta = schema.load_file(art / 'metadata.toml')
    assert meta.wall_seconds == 0.0
    assert meta.exit_code == 0
    assert meta.notes == ''


# --- Failure cleanup (HIGH-2-B 行 51, 53) -------------------------------------


def test_cfg_resolved_write_failure_rmtree_orphan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If cfg_resolved.toml write raises, the per-run dir must be
    rmtree'd before propagating SystemExit(2)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'fail_resolved')
    state = setup_mod.phase_a_setup(_make_args(cfg))
    art = state.artifacts_dir
    assert art.is_dir()

    real_write_text = Path.write_text

    def patched_write_text(self: Path, *a: Any, **kw: Any) -> int:  # noqa: ANN401
        if self.name == 'cfg_resolved.toml':
            raise OSError('simulated disk full')
        return real_write_text(self, *a, **kw)

    monkeypatch.setattr(Path, 'write_text', patched_write_text)
    with pytest.raises(SystemExit) as ei:
        snapshot_mod.phase_b_write_cfg_metadata(state, Path(state.artifacts_dir.parent.parent) / 'cfg.toml')
    assert ei.value.code == 2
    assert not art.exists(), 'orphan dir survived after cfg_resolved write failure'


def test_metadata_write_failure_rmtree_orphan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If write_metadata_atomic raises, dir must be rmtree'd + SystemExit(2)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'fail_meta')
    state = setup_mod.phase_a_setup(_make_args(cfg))
    art = state.artifacts_dir

    def boom(*a: Any, **kw: Any) -> None:  # noqa: ANN401
        raise OSError('simulated metadata write fail')

    monkeypatch.setattr(snapshot_mod, 'write_metadata_atomic', boom)
    with pytest.raises(SystemExit) as ei:
        snapshot_mod.phase_b_write_cfg_metadata(state, cfg)
    assert ei.value.code == 2
    assert not art.exists(), 'orphan dir survived after metadata write failure'


def test_cfg_leaf_write_failure_rmtree_orphan(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """First write (cfg_leaf.toml) failure also triggers cleanup."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'fail_leaf')
    state = setup_mod.phase_a_setup(_make_args(cfg))
    art = state.artifacts_dir

    real_write_bytes = Path.write_bytes

    def patched_write_bytes(self: Path, *a: Any, **kw: Any) -> int:  # noqa: ANN401
        if self.name == 'cfg_leaf.toml':
            raise OSError('simulated leaf write fail')
        return real_write_bytes(self, *a, **kw)

    monkeypatch.setattr(Path, 'write_bytes', patched_write_bytes)
    with pytest.raises(SystemExit) as ei:
        snapshot_mod.phase_b_write_cfg_metadata(state, cfg)
    assert ei.value.code == 2
    assert not art.exists()


def test_cleanup_failure_logs_but_does_not_mask_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """spec 行 301 — finally try/except cleanup error never replaces
    the in-flight train exception; cleanup goes to stderr as a
    diagnostic only."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'cleanup_fail')
    state = setup_mod.phase_a_setup(_make_args(cfg))

    def boom_meta(*a: Any, **kw: Any) -> None:  # noqa: ANN401
        raise OSError('original write failure')

    def boom_rmtree(*a: Any, **kw: Any) -> None:  # noqa: ANN401
        raise OSError('cleanup also failed')

    monkeypatch.setattr(snapshot_mod, 'write_metadata_atomic', boom_meta)
    monkeypatch.setattr(snapshot_mod.shutil, 'rmtree', boom_rmtree)
    with pytest.raises(SystemExit) as ei:
        snapshot_mod.phase_b_write_cfg_metadata(state, cfg)
    assert ei.value.code == 2
    err = capsys.readouterr().err
    # Both errors visible — cleanup failure as warning, original as
    # the SystemExit cause / log line.
    assert 'cleanup failed' in err
    assert 'original write failure' in err


def test_phase_b_propagates_systemexit_unwrapped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the underlying failure is already a SystemExit (e.g. caller
    raised one directly), Phase B must not double-wrap it — preserves
    the original exit code."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'systemexit_pass')
    state = setup_mod.phase_a_setup(_make_args(cfg))

    def raise_systemexit(*a: Any, **kw: Any) -> None:  # noqa: ANN401
        raise SystemExit(7)

    monkeypatch.setattr(snapshot_mod, 'write_metadata_atomic', raise_systemexit)
    with pytest.raises(SystemExit) as ei:
        snapshot_mod.phase_b_write_cfg_metadata(state, cfg)
    # Original exit code 7 preserved (not 2).
    assert ei.value.code == 7


# --- Phase A + B integration via main() --------------------------------------


def test_main_runs_phase_a_and_b_and_writes_all_three_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # T-11: stub real-dispatch placeholder; this test scopes to "A+B+close",
    # paradigm dispatch e2e lives in test_train_dispatch_smoke.py.
    from tools.runs._train import run as run_mod

    monkeypatch.setattr(run_mod, '_run_train_placeholder', lambda _state: None)
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'integration')
    rc = train_mod.main([str(cfg)])
    assert rc == 0
    # Locate the per-run dir (single child of artifacts/).
    children = list((tmp_path / 'artifacts').iterdir())
    art_dirs = [c for c in children if c.is_dir()]
    assert len(art_dirs) == 1
    art = art_dirs[0]
    assert (art / 'cfg_leaf.toml').is_file()
    assert (art / 'cfg_resolved.toml').is_file()
    assert (art / 'metadata.toml').is_file()
    meta = schema.load_file(art / 'metadata.toml')
    # Post T-10 main() runs Phase C which closes to 'done'. Phase-C-
    # specific close behavior lives in test_train_close.py.
    assert meta.status == 'done'


def test_main_exits_2_when_phase_b_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If Phase B raises, main() must surface exit 2 (SystemExit
    propagates, the orphan dir is cleaned by Phase B itself)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'main_phase_b_fail')

    # Patch the snapshot module's write_metadata_atomic to force a
    # Phase B failure; verify the SystemExit propagates with code 2.
    def boom(*a: Any, **kw: Any) -> None:  # noqa: ANN401
        raise OSError('simulated phase B fail')

    monkeypatch.setattr(snapshot_mod, 'write_metadata_atomic', boom)
    with pytest.raises(SystemExit) as ei:
        train_mod.main([str(cfg)])
    assert ei.value.code == 2
    # Verify the orphan dir was cleaned (Phase B's responsibility).
    art_dirs = list((tmp_path / 'artifacts').iterdir()) if (tmp_path / 'artifacts').exists() else []
    assert not [c for c in art_dirs if c.is_dir()]


# --- Round-trip verify safety net (emitter unit tests in test_train_cfg_toml.py;
# checks below cover the wrapper's catch of parse failure + value mismatch). ---


def test_round_trip_verify_catches_mismatch() -> None:
    with pytest.raises(RuntimeError, match='round-trip mismatch'):
        snapshot_mod._verify_round_trip('a = 1\n', {'a': 2})


def test_round_trip_verify_catches_parse_failure() -> None:
    with pytest.raises(RuntimeError, match='non-parseable'):
        snapshot_mod._verify_round_trip('this is = not valid toml [[[', {'a': 1})
