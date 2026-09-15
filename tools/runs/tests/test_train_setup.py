"""Tests for tools.runs.train Phase A (T-08) — lifecycle steps 0-3.

Covers spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`` (主卷)
+ ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design-rollout.md`` (续卷):

- §Architecture step 0-3
- CRIT-1-B run_label regex
- HIGH-2-A artifacts mkdir
- CRIT-1-A 临界区 mkdir-O_EXCL
- HIGH-1-A dir-name <label> = resolved cfg.meta.run_label
- HIGH-X-3 UTC ts single-sourced (dir name ↔ state.timestamp_utc)
- HIGH-2-B cleanup rmtree on orphan

Phase B/C (T-09/T-10) lifecycle steps 4-7 are out of scope — those
tests live in test_train_phase_b.py / test_train_phase_c.py once those
land.
"""

from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from tools.runs import train as train_mod
from tools.runs._train import setup as setup_mod


# --- Fixtures -----------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Train uses ``Path.cwd()`` to root ``artifacts/``. Each test gets
    a fresh empty tmp tree as its cwd so they don't share artifacts/.

    Materialize ``tools/runs/`` under tmp_path so the ``_verify_repo_root``
    guard (added in T-08 quality-review M-1 fix) accepts the fake cwd.
    The dedicated ``test_setup_rejects_non_repo_cwd`` test below opts
    out via its own monkeypatch.chdir to verify the guard fires.
    """
    (tmp_path / 'tools' / 'runs').mkdir(parents=True)
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _write_cfg(path: Path, run_label: str, *, extra: str = '', paradigm: str = 'dmc') -> Path:
    """Write a minimal TOML cfg with ``meta.run_label`` set.

    Only writes ``[meta]`` + caller's ``extra`` so phase A's resolve
    step (load_with_extends) doesn't need a full TrainingConfig schema —
    Phase A intentionally skips schema validation (T-11 scope).
    """
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
    """Build a Namespace mimicking _parse_args output."""
    import argparse

    return argparse.Namespace(
        cfg=str(cfg),
        override=list(kw.get('override', [])),
        resume=kw.get('resume'),
    )


# --- Repo-root guard (T-08 quality review M-1) -------------------------------


def test_setup_rejects_non_repo_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Guard fires when cwd does not contain ``tools/runs/`` — prevents
    silent misdirection of ``artifacts/`` when caller runs from a subdir.
    """
    bare = tmp_path / 'bare_dir'
    bare.mkdir()
    # Opt out of the autouse fixture's tools/runs/ marker by chdir-ing
    # to a sibling dir without the marker.
    monkeypatch.chdir(bare)
    cfg = bare / 'cfg.toml'
    cfg.write_text('[meta]\nrun_label = "any"\n')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg))
    # SystemExit args is the message string (passed positionally), not a
    # numeric code — verify the diagnostic mentions the missing marker.
    assert 'tools/runs/' in str(ei.value)


# --- Step 0: run_label regex validate (leaf + post-resolve) -------------------


def test_setup_passes_with_valid_run_label(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'valid_label-123')
    state = train_mod._phase_a_setup(_make_args(cfg))
    assert state.label == 'valid_label-123'
    assert state.artifacts_dir.exists()


@pytest.mark.parametrize(
    'bad_label',
    [
        '../etc',  # path traversal
        '../../escape',  # multi-level traversal
        '',  # empty
        'a' * 65,  # over 64
        'with space',  # space (not in charset)
        'foo/bar',  # forward slash
        'foo\\bar',  # backslash
        'foo;bar',  # shell metachar
        'foo$bar',  # shell metachar
        'foo`bar',  # shell metachar
        'foo|bar',  # shell metachar
        'foo&bar',  # shell metachar
        'foo.bar',  # dot (not in charset)
    ],
)
def test_setup_rejects_invalid_run_label_in_leaf(tmp_path: Path, bad_label: str) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', bad_label)
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg))
    assert ei.value.code == 2


def test_setup_rejection_stderr_includes_spec_regex(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', '../etc')
    with pytest.raises(SystemExit):
        train_mod._phase_a_setup(_make_args(cfg))
    err = capsys.readouterr().err
    assert 'run_label' in err
    # Verify the spec regex literal appears in the error message (so
    # operators see the exact wording from spec §单命令 atomic lifecycle).
    assert '^[a-zA-Z0-9_-]{1,64}$' in err


def test_setup_rejects_override_meta_run_label_traversal(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Override that injects bad run_label must be caught by the
    POST-resolve validate (spec §单命令 atomic lifecycle — dir name uses post-override
    value)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'safe_label')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg, override=['meta.run_label=../etc']))
    assert ei.value.code == 2
    err = capsys.readouterr().err
    # Must reference the *resolved* source label, not the *leaf* one
    # — proves the post-resolve check fired (not the leaf-only).
    assert 'resolved cfg.meta.run_label' in err


def test_setup_rejects_override_meta_run_label_empty(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'safe_label')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg, override=['meta.run_label=']))
    assert ei.value.code == 2


# --- Step 1: capture leaf cfg bytes -------------------------------------------


def test_setup_captures_leaf_bytes(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'label1')
    original_bytes = cfg.read_bytes()
    state = train_mod._phase_a_setup(_make_args(cfg))
    assert state.cfg_leaf_bytes == original_bytes


def test_setup_leaf_bytes_immune_to_post_setup_cfg_edit(tmp_path: Path) -> None:
    """Edit cfg file after setup completes — captured bytes must reflect
    the original content (proves read happened in step 1 not on demand)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'label1')
    state = train_mod._phase_a_setup(_make_args(cfg))
    captured_before_edit = state.cfg_leaf_bytes
    cfg.write_text('# mutated post-setup\n[meta]\nrun_label = "new"\n')
    # Bytes on the SetupState are still pre-edit.
    assert state.cfg_leaf_bytes == captured_before_edit
    assert b'mutated' not in state.cfg_leaf_bytes


# --- Step 2: resolve + override -----------------------------------------------


def test_setup_resolves_extends_chain(tmp_path: Path) -> None:
    """Child cfg extends parent — resolved dict reflects merged result."""
    parent = tmp_path / 'parent.toml'
    parent.write_text("""
[meta]
seed = 99
paradigm = "dmc"
run_label = "parent_label"

[pipeline]
mode = "serial"
""")
    child = tmp_path / 'child.toml'
    child.write_text("""
[meta]
extends = "parent.toml"
run_label = "child_label"
""")
    state = train_mod._phase_a_setup(_make_args(child))
    # Inherited from parent.
    assert state.cfg_resolved['meta']['seed'] == 99
    assert state.cfg_resolved['pipeline']['mode'] == 'serial'
    # Overridden by child.
    assert state.cfg_resolved['meta']['run_label'] == 'child_label'
    assert state.label == 'child_label'


def test_setup_applies_override(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'safe', extra='[paradigm.az]\nbatch_size = 64')
    state = train_mod._phase_a_setup(_make_args(cfg, override=['paradigm.az.batch_size=128']))
    assert state.cfg_resolved['paradigm']['az']['batch_size'] == 128


def test_setup_override_changes_dir_label(tmp_path: Path) -> None:
    """spec §单命令 atomic lifecycle — dir name uses POST-override label, not leaf cfg field."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'original_label')
    state = train_mod._phase_a_setup(_make_args(cfg, override=['meta.run_label=overridden']))
    assert state.label == 'overridden'
    assert '_overridden' in state.artifacts_dir.name
    assert 'original_label' not in state.artifacts_dir.name


def test_setup_malformed_override_raises_systemexit_2(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'safe')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg, override=['no_equals_sign']))
    assert ei.value.code == 2


def test_setup_missing_cfg_raises_systemexit_2(tmp_path: Path) -> None:
    missing = tmp_path / 'nope.toml'
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(missing))
    assert ei.value.code == 2


def test_setup_cfg_pointing_to_dir_raises(tmp_path: Path) -> None:
    d = tmp_path / 'a_dir'
    d.mkdir()
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(d))
    assert ei.value.code == 2


def test_setup_malformed_toml_raises_systemexit_2(tmp_path: Path) -> None:
    cfg = tmp_path / 'broken.toml'
    cfg.write_text('this is = not valid toml [[[')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg))
    assert ei.value.code == 2


def test_setup_missing_meta_section_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / 'no_meta.toml'
    cfg.write_text('[other]\nfoo = "bar"\n')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg))
    assert ei.value.code == 2


def test_setup_non_string_run_label_rejected(tmp_path: Path) -> None:
    cfg = tmp_path / 'bad_type.toml'
    cfg.write_text('[meta]\nrun_label = 42\n')
    with pytest.raises(SystemExit) as ei:
        train_mod._phase_a_setup(_make_args(cfg))
    assert ei.value.code == 2


# --- Step 2.5 + Step 3: artifacts/ mkdir + allocator + per-run mkdir ---------


def test_setup_creates_artifacts_dir_when_missing(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'label1')
    assert not (tmp_path / 'artifacts').exists()
    state = train_mod._phase_a_setup(_make_args(cfg))
    assert (tmp_path / 'artifacts').is_dir()
    assert state.artifacts_dir.parent == tmp_path / 'artifacts'


def test_setup_first_run_assigns_nnn_1(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'label1')
    state = train_mod._phase_a_setup(_make_args(cfg))
    assert state.nnn == 1
    # Dir name 6-digit zero-padded NNN.
    assert re.match(r'^\d{12}_000001_label1$', state.artifacts_dir.name)


def test_setup_picks_max_plus_one_from_existing(tmp_path: Path) -> None:
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    (artifacts / '202605180000_000005_other').mkdir()
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'newrun')
    state = train_mod._phase_a_setup(_make_args(cfg))
    assert state.nnn == 6


def test_setup_per_run_dir_exists_after_setup(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'lbl')
    state = train_mod._phase_a_setup(_make_args(cfg))
    assert state.artifacts_dir.is_dir()


def test_setup_dir_name_format_matches_spec(tmp_path: Path) -> None:
    """spec dir name: ``<YYYYMMDDHHMM>_<NNNNNN>_<label>/``."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'my_label-1')
    state = train_mod._phase_a_setup(_make_args(cfg))
    name = state.artifacts_dir.name
    m = re.match(r'^(\d{12})_(\d{6})_(.+)$', name)
    assert m is not None, f'dir name {name!r} does not match spec'
    assert int(m.group(2)) == state.nnn
    assert m.group(3) == 'my_label-1'


def test_setup_eexist_retry_advances_to_next_nnn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Inject a one-shot FileExistsError on the first mkdir attempt;
    setup must retry (allocator re-glob → next NNN) and finally succeed.
    """
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'lbl')

    real_mkdir = Path.mkdir
    call_count = {'n': 0}

    def fake_mkdir(self: Path, *a: Any, **kw: Any) -> Any:  # noqa: ANN401
        # Only fail the per-run dir creation (parents=False, exist_ok=False)
        # — the artifacts/ mkdir call uses parents=True, exist_ok=True.
        if kw.get('parents') is False and kw.get('exist_ok') is False:
            call_count['n'] += 1
            if call_count['n'] == 1:
                # Simulate: someone else's dir already occupies this name.
                # Materialize the dir so allocator re-glob picks NNN+1.
                real_mkdir(self, *a, **kw)
                raise FileExistsError(f'simulated collide on {self}')
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, 'mkdir', fake_mkdir)
    state = train_mod._phase_a_setup(_make_args(cfg))
    # First attempt at NNN=1 hit (simulated) EEXIST; second attempt at
    # NNN=2 succeeded.
    assert state.nnn == 2
    assert call_count['n'] >= 2


def test_setup_eexist_loop_bounded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If mkdir always EEXIST, the outer retry loop must terminate
    (not infinite-spin) and raise."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'lbl')
    real_mkdir = Path.mkdir

    def always_eexist(self: Path, *a: Any, **kw: Any) -> Any:  # noqa: ANN401
        if kw.get('parents') is False and kw.get('exist_ok') is False:
            # Materialize the dir so allocator's re-glob makes forward
            # progress on NNN; otherwise the EEXIST scenario isn't
            # "collide every time" but rather "always fail mkdir even
            # when target doesn't exist", which is a different bug.
            real_mkdir(self, *a, **kw)
            raise FileExistsError(f'simulated permanent collide on {self}')
        return real_mkdir(self, *a, **kw)

    monkeypatch.setattr(Path, 'mkdir', always_eexist)
    with pytest.raises((RuntimeError, SystemExit)):
        train_mod._phase_a_setup(_make_args(cfg))


# --- UTC ts single-source -----------------------------------------------------


def test_setup_ts_in_dir_name_matches_state_timestamp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """spec §单命令 atomic lifecycle — dir name ts and state.timestamp_utc derive from a
    single source. Monkeypatch datetime.now to a fixed UTC value, then
    verify both representations are consistent."""
    fixed = datetime(2026, 5, 18, 3, 55, 17, 123456, tzinfo=timezone.utc)

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> 'datetime':  # noqa: ANN401
            assert tz == timezone.utc, 'spec requires UTC at the source'
            return fixed

    monkeypatch.setattr(setup_mod, 'datetime', _FakeDatetime)
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'utc_test')
    state = train_mod._phase_a_setup(_make_args(cfg))
    # Both views derived from `fixed` → identical strftime.
    assert state.timestamp_utc.strftime('%Y%m%d%H%M') == '202605180355'
    assert state.artifacts_dir.name.startswith('202605180355_')
    # state.timestamp_utc must be sub-minute-truncated (seconds=0,
    # microseconds=0) so it round-trips through ``%Y%m%d%H%M`` without
    # silently dropping precision.
    assert state.timestamp_utc.second == 0
    assert state.timestamp_utc.microsecond == 0
    assert state.timestamp_utc.tzinfo == timezone.utc


def test_setup_uses_utc_not_local(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """If implementation accidentally drops tz or uses local time, the
    asserted tz argument on now() would fail."""
    seen_tzs: list[Any] = []

    real_now = datetime.now

    class _CaptureDatetime(datetime):
        @classmethod
        def now(cls, tz: Any = None) -> 'datetime':  # noqa: ANN401
            seen_tzs.append(tz)
            return real_now(tz)

    monkeypatch.setattr(setup_mod, 'datetime', _CaptureDatetime)
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'utc_only')
    train_mod._phase_a_setup(_make_args(cfg))
    assert seen_tzs, 'datetime.now never called'
    assert all(tz == timezone.utc for tz in seen_tzs), f'non-UTC calls: {seen_tzs}'


# --- Failure cleanup ----------------------------------------------------------


def test_setup_orphan_dir_rmtree_on_assembly_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate SetupState construction failing AFTER per-run mkdir
    succeeded — orphan dir must be rmtree'd (spec §单命令 atomic lifecycle)."""
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'lbl')

    real_setup_state = setup_mod.SetupState
    dirs_created: list[Path] = []

    def exploding_state(**kw: Any) -> Any:  # noqa: ANN401
        dirs_created.append(kw['artifacts_dir'])
        raise RuntimeError('simulated state assembly failure')

    monkeypatch.setattr(setup_mod, 'SetupState', exploding_state)
    try:
        with pytest.raises(RuntimeError, match='simulated state assembly failure'):
            train_mod._phase_a_setup(_make_args(cfg))
    finally:
        monkeypatch.setattr(setup_mod, 'SetupState', real_setup_state)

    assert dirs_created, 'mkdir of per-run dir never happened'
    # The orphan dir created before the failure must be cleaned up.
    for d in dirs_created:
        assert not d.exists(), f'orphan dir not cleaned: {d}'


# --- SetupState dataclass shape ----------------------------------------------


def test_setup_state_has_eight_documented_fields(tmp_path: Path) -> None:
    """SetupState shape: 6 fresh-path fields + 2 resume-context (T-12).

    Resume fields default to ``cfg_resolved_version=1`` /
    ``resume_ckpt_path=None`` so fresh-path callers don't pass them.
    Resume Phase A builds with both populated.
    """
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'shape_check')
    state = train_mod._phase_a_setup(_make_args(cfg))
    # Frozen dataclass → __dataclass_fields__ is the source of truth.
    fields = set(train_mod.SetupState.__dataclass_fields__.keys())
    assert fields == {
        'artifacts_dir',
        'cfg_resolved',
        'cfg_leaf_bytes',
        'nnn',
        'label',
        'timestamp_utc',
        'cfg_resolved_version',
        'resume_ckpt_path',
    }
    # Spot-check types on the live instance.
    assert isinstance(state.artifacts_dir, Path)
    assert isinstance(state.cfg_resolved, dict)
    assert isinstance(state.cfg_leaf_bytes, bytes)
    assert isinstance(state.nnn, int) and state.nnn >= 1
    assert isinstance(state.label, str)
    assert isinstance(state.timestamp_utc, datetime)
    # Fresh path defaults: version=1, no resume ckpt.
    assert state.cfg_resolved_version == 1
    assert state.resume_ckpt_path is None


def test_setup_state_is_frozen(tmp_path: Path) -> None:
    cfg = _write_cfg(tmp_path / 'cfg.toml', 'frozen_check')
    state = train_mod._phase_a_setup(_make_args(cfg))
    with pytest.raises((FrozenInstanceError, AttributeError)):
        state.nnn = 999  # type: ignore[misc]


# NOTE: ``main()`` + ``_parse_args`` integration tests live in
# ``test_train_main.py`` (T-10 housekeeping split — file was at 530/500
# after T-09 landed). Phase-A-only unit tests stay here.
