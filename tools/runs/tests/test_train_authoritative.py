"""T-13 authoritative host enforcement tests.

Spec ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§HIGH-2-D:

- Marker file ``artifacts/.authoritative_host`` absent → allow (§HIGH-2-D)
- Marker content == current ``socket.gethostname()`` → allow (§HIGH-2-D)
- Marker content != hostname → ``SystemExit(2)`` + spec §HIGH-2-D wording
  (``'this host is pull-only; cannot allocate new NNN. To make this
  host authoritative, run tools.runs.sync init-authoritative'``)

Both the fresh path (:func:`phase_a_setup`) and the resume path
(:func:`phase_a_resume`) call ``_verify_authoritative_host``;
both are covered here.

The ``tools.runs.sync init-authoritative`` CLI subcommand referenced
in the error message is T-19 scope and is NOT exercised by this file.
"""

from __future__ import annotations

import socket
from pathlib import Path

import pytest

from tools.runs import schema, train as train_mod
from tools.runs._train import setup as setup_mod
from tools.runs.tests._resume_fixtures import (
    fresh_train,
    isolate_cwd,  # noqa: F401 — autouse via wrapper below
    make_dummy_ckpt,
    stub_train,  # noqa: F401 — autouse via wrapper below
    write_cfg,
)


@pytest.fixture(autouse=True)
def _isolate_cwd(isolate_cwd: Path) -> Path:  # noqa: F811
    return isolate_cwd


@pytest.fixture(autouse=True)
def _stub_train(stub_train: None) -> None:  # noqa: F811
    pass


def _write_marker(tmp_path: Path, content: str) -> Path:
    """Create ``artifacts/.authoritative_host`` with raw bytes content.

    ``artifacts/`` is created on demand — fresh-cwd fixture starts empty.
    Returns the marker path for assertion convenience.
    """
    artifacts_root = tmp_path / 'artifacts'
    artifacts_root.mkdir(parents=True, exist_ok=True)
    marker = artifacts_root / '.authoritative_host'
    marker.write_text(content, encoding='utf-8')
    return marker


# --- Direct helper tests ------------------------------------------------------


def test_verify_allows_when_marker_missing(tmp_path: Path) -> None:
    """Spec §HIGH-2-D — marker absent => no-op (initial / unrestricted mode)."""
    # No marker written. Helper should return cleanly.
    setup_mod._verify_authoritative_host(tmp_path)


def test_verify_allows_when_marker_matches_hostname(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Spec §HIGH-2-D — marker == socket.gethostname() => allow."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'fake-mac.local')
    _write_marker(tmp_path, 'fake-mac.local')
    setup_mod._verify_authoritative_host(tmp_path)


def test_verify_strips_trailing_whitespace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """``echo $(hostname) > marker`` leaves a trailing ``\\n`` — must
    not cause a false mismatch with the bare-string hostname."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'fake-mac.local')
    _write_marker(tmp_path, 'fake-mac.local\n')
    setup_mod._verify_authoritative_host(tmp_path)
    # Also try leading/trailing whitespace + CRLF.
    _write_marker(tmp_path, '  fake-mac.local  \r\n')
    setup_mod._verify_authoritative_host(tmp_path)


def test_verify_raises_when_marker_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Spec §HIGH-2-D — mismatch => SystemExit(2) with pinned wording."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'fake-mac.local')
    _write_marker(tmp_path, 'other-host')
    with pytest.raises(SystemExit) as excinfo:
        setup_mod._verify_authoritative_host(tmp_path)
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    # Pinned wording from spec §HIGH-2-D.
    assert 'this host is pull-only' in stderr
    assert 'tools.runs.sync init-authoritative' in stderr
    # Diagnostic detail (marker + hostname) so operator can debug.
    assert 'other-host' in stderr
    assert 'fake-mac.local' in stderr


def test_verify_raises_on_empty_marker(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Empty file => content.strip() == '' which != any hostname.
    Treated as malformed marker; raise rather than silently allow."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'fake-mac.local')
    _write_marker(tmp_path, '')
    with pytest.raises(SystemExit) as excinfo:
        setup_mod._verify_authoritative_host(tmp_path)
    assert excinfo.value.code == 2


# --- Fresh-path integration ---------------------------------------------------


def test_fresh_train_allowed_when_marker_missing(tmp_path: Path) -> None:
    """Fresh ``main()`` succeeds when no authoritative marker is set
    (initial-state default)."""
    cfg = write_cfg(tmp_path / 'cfg.toml', 'auth_test')
    rc = train_mod.main([str(cfg)])
    assert rc == 0


def test_fresh_train_allowed_when_marker_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh ``main()`` succeeds when marker matches the current host."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'authoritative-host')
    _write_marker(tmp_path, 'authoritative-host')
    cfg = write_cfg(tmp_path / 'cfg.toml', 'auth_test')
    rc = train_mod.main([str(cfg)])
    assert rc == 0


def test_fresh_train_rejected_on_pull_only_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Spec §HIGH-2-D — fresh path on a pull-only replica => SystemExit(2)
    and NO per-run dir mkdir happens (rejection is pre-allocator)."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'replica-host')
    _write_marker(tmp_path, 'authoritative-host')
    cfg = write_cfg(tmp_path / 'cfg.toml', 'auth_test')
    with pytest.raises(SystemExit) as excinfo:
        train_mod.main([str(cfg)])
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    assert 'this host is pull-only' in stderr
    assert 'tools.runs.sync init-authoritative' in stderr
    # No artifacts run-dir created (allocator never ran).
    run_dirs = [p for p in (tmp_path / 'artifacts').iterdir() if p.is_dir() and not p.name.startswith('.')]
    assert run_dirs == []


def test_fresh_train_marker_with_trailing_newline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """End-to-end version of the strip test — marker written via the
    ``echo > file`` idiom (trailing ``\\n``) does not block the
    authoritative host."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'authoritative-host')
    _write_marker(tmp_path, 'authoritative-host\n')
    cfg = write_cfg(tmp_path / 'cfg.toml', 'auth_test')
    rc = train_mod.main([str(cfg)])
    assert rc == 0


# --- Resume-path integration --------------------------------------------------


def test_resume_allowed_when_marker_missing(tmp_path: Path) -> None:
    """Resume succeeds when no authoritative marker is set (matches
    fresh-path behavior — marker absent = unrestricted mode)."""
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    rc = train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert rc == 0


def test_resume_allowed_when_marker_matches(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Resume succeeds when marker matches current host."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'authoritative-host')
    # fresh_train runs train_mod.main → goes through the host check;
    # write the marker BEFORE fresh_train so both calls observe it.
    _write_marker(tmp_path, 'authoritative-host')
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    rc = train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert rc == 0


def test_resume_rejected_on_pull_only_host(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    """Resume on a pull-only replica => SystemExit(2). metadata.toml
    is NOT mutated (cfg_resolved_version stays at 1 from fresh train).
    """
    # First: fresh-train as the authoritative host (no marker present
    # yet so the host check is a no-op).
    cfg, art = fresh_train(tmp_path)
    ckpt = make_dummy_ckpt(art)
    pre_version = schema.load_file(art / 'metadata.toml').cfg_resolved_version

    # Then: install a marker for a different host + try to resume.
    monkeypatch.setattr(socket, 'gethostname', lambda: 'replica-host')
    _write_marker(tmp_path, 'authoritative-host')

    with pytest.raises(SystemExit) as excinfo:
        train_mod.main([str(cfg), '--resume', str(ckpt)])
    assert excinfo.value.code == 2
    stderr = capsys.readouterr().err
    assert 'this host is pull-only' in stderr

    # Metadata untouched — version stayed at fresh-path v1, no v2 file
    # accidentally written before the host check rejected.
    post_version = schema.load_file(art / 'metadata.toml').cfg_resolved_version
    assert post_version == pre_version
    assert not (art / 'cfg_resolved_v2.toml').exists()
    assert not (art / 'cfg_leaf_v2.toml').exists()


# --- Re-export sanity ---------------------------------------------------------


def test_helper_reexported_from_public_train_module() -> None:
    """``tools.runs.train._verify_authoritative_host`` must alias the
    canonical setup-module definition (preserves the public underscored
    surface used by other tests / future Phase callers)."""
    assert train_mod._verify_authoritative_host is setup_mod._verify_authoritative_host
