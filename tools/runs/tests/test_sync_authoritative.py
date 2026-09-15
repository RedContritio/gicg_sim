"""Tests for ``tools.runs.sync init-authoritative`` (T-19).

Covers spec §HIGH-2-D — write
``<repo_root>/artifacts/.authoritative_host`` = current
``socket.gethostname()``. Marker is consumed by
``tools.runs._train.setup._verify_authoritative_host`` (T-13); the round-
trip is asserted here so the two halves stay in sync (writer/reader
contract: bare hostname + trailing newline, UTF-8).

Three layers:
- ``init_authoritative`` pure function — file content + mkdir behaviour
- CLI dispatch via ``sync.main([..., 'init-authoritative'])``
- Subprocess module entry point ``python -m tools.runs.sync init-authoritative``
"""

from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs import sync
from tools.runs._helpers import sync_extras
from tools.runs._train import setup as setup_mod


# ---------------------------------------------------------------------------
# init_authoritative — pure function
# ---------------------------------------------------------------------------


def test_init_authoritative_writes_marker_with_hostname(tmp_path):
    marker = sync_extras.init_authoritative(tmp_path, hostname='laptop-01')
    assert marker == tmp_path / 'artifacts' / '.authoritative_host'
    assert marker.exists()
    content = marker.read_text(encoding='utf-8')
    assert content == 'laptop-01\n'


def test_init_authoritative_creates_artifacts_dir_when_missing(tmp_path):
    assert not (tmp_path / 'artifacts').exists()
    sync_extras.init_authoritative(tmp_path, hostname='hostA')
    assert (tmp_path / 'artifacts').is_dir()


def test_init_authoritative_overwrites_existing_marker(tmp_path):
    """Spec §HIGH-2-D — overwrite is intentional (user decision)."""
    sync_extras.init_authoritative(tmp_path, hostname='old-host')
    sync_extras.init_authoritative(tmp_path, hostname='new-host')
    marker = tmp_path / 'artifacts' / '.authoritative_host'
    assert marker.read_text(encoding='utf-8') == 'new-host\n'


def test_init_authoritative_default_hostname_uses_socket(tmp_path, monkeypatch):
    monkeypatch.setattr(socket, 'gethostname', lambda: 'mocked-host')
    sync_extras.init_authoritative(tmp_path)
    marker = tmp_path / 'artifacts' / '.authoritative_host'
    assert marker.read_text(encoding='utf-8') == 'mocked-host\n'


def test_init_authoritative_returns_absolute_path(tmp_path):
    marker = sync_extras.init_authoritative(tmp_path, hostname='h')
    assert marker.is_absolute()


# ---------------------------------------------------------------------------
# Re-export — sync.init_authoritative aliases sync_extras.init_authoritative
# ---------------------------------------------------------------------------


def test_sync_init_authoritative_is_same_function():
    assert sync.init_authoritative is sync_extras.init_authoritative


# ---------------------------------------------------------------------------
# CLI dispatch via sync.main
# ---------------------------------------------------------------------------


def test_main_init_authoritative_writes_marker(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(socket, 'gethostname', lambda: 'cli-host')
    rc = sync.main(['init-authoritative', '--root', str(tmp_path)])
    assert rc == 0
    marker = tmp_path / 'artifacts' / '.authoritative_host'
    assert marker.read_text(encoding='utf-8') == 'cli-host\n'
    err = capsys.readouterr().err
    assert 'authoritative host set' in err
    assert 'cli-host' in err


def test_main_init_authoritative_rejects_remote_arg(tmp_path, capsys):
    rc = sync.main(['init-authoritative', 'u@h:/p/', '--root', str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert 'init-authoritative takes no remote' in err


def test_main_push_requires_remote(tmp_path, capsys):
    rc = sync.main(['push', '--root', str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert 'requires a remote' in err


def test_main_pull_requires_remote(tmp_path, capsys):
    rc = sync.main(['pull', '--root', str(tmp_path)])
    assert rc == 1
    err = capsys.readouterr().err
    assert 'requires a remote' in err


# ---------------------------------------------------------------------------
# Subprocess module entry point
# ---------------------------------------------------------------------------


def test_main_subprocess_init_authoritative(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            '-m',
            'tools.runs.sync',
            'init-authoritative',
            '--root',
            str(tmp_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        cwd=Path(__file__).resolve().parents[3],
    )
    assert result.returncode == 0, result.stderr
    marker = tmp_path / 'artifacts' / '.authoritative_host'
    assert marker.exists()
    # Real hostname (no monkeypatch in subprocess); just verify non-empty.
    content = marker.read_text(encoding='utf-8')
    assert content.endswith('\n')
    assert len(content.strip()) > 0


# ---------------------------------------------------------------------------
# Round-trip with consumer (T-13 ``_verify_authoritative_host``)
# ---------------------------------------------------------------------------


def test_init_then_verify_same_host_allows(tmp_path, monkeypatch):
    """``init_authoritative`` writes a marker that ``_verify_authoritative_host``
    accepts when the hostname matches. Locks the writer/reader format
    (bare hostname + trailing newline, UTF-8)."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'host-A')
    sync_extras.init_authoritative(tmp_path)
    # consumer reads + strips newline + compares to gethostname()
    setup_mod._verify_authoritative_host(tmp_path)  # no raise → contract holds


def test_init_then_verify_different_host_raises(tmp_path, monkeypatch):
    """init under host A, then a host-B consumer must hit the SystemExit
    (T-13 enforce) — proves the marker travels through the contract."""
    monkeypatch.setattr(socket, 'gethostname', lambda: 'host-A')
    sync_extras.init_authoritative(tmp_path)
    monkeypatch.setattr(socket, 'gethostname', lambda: 'host-B')
    with pytest.raises(SystemExit) as exc_info:
        setup_mod._verify_authoritative_host(tmp_path)
    assert exc_info.value.code == 2
