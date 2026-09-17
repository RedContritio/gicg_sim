"""Tests for cfg-driven checkpoint pulls in ``tools.eval.daemon``."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import patch

from tools.eval import daemon
from tools.runs._host import RemoteCfg


REMOTE = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='remote-host')


def _cp(returncode: int = 0, stderr: str = '') -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=returncode, stdout='', stderr=stderr)


def test_pull_latest_local_is_noop(tmp_path: Path):
    run_dir = tmp_path / 'run'
    assert daemon._pull_latest(None, run_dir, 'run') == 0
    assert not (run_dir / 'ckpts').exists()


def test_pull_latest_atomically_replaces_checkpoint(tmp_path: Path):
    run_dir = tmp_path / 'run'
    ckpt_dir = run_dir / 'ckpts'
    ckpt_dir.mkdir(parents=True)
    latest = ckpt_dir / 'latest.pt'
    latest.write_bytes(b'old')

    def fake_scp(remote, remote_rel, local, timeout, *, preserve):
        assert remote == REMOTE
        assert remote_rel == 'artifacts/run/ckpts/latest.pt'
        assert timeout == 300
        assert preserve is True
        Path(local).write_bytes(b'new')
        return _cp()

    with patch('tools.eval.daemon.scp_from', side_effect=fake_scp):
        assert daemon._pull_latest(REMOTE, run_dir, 'run') == 0

    assert latest.read_bytes() == b'new'
    assert not list(ckpt_dir.glob('.latest.*.pt'))


def test_pull_latest_failure_preserves_previous_checkpoint(tmp_path: Path):
    run_dir = tmp_path / 'run'
    ckpt_dir = run_dir / 'ckpts'
    ckpt_dir.mkdir(parents=True)
    latest = ckpt_dir / 'latest.pt'
    latest.write_bytes(b'old')

    def fake_scp(remote, remote_rel, local, timeout, *, preserve):
        Path(local).write_bytes(b'partial')
        return _cp(returncode=7, stderr='permission denied')

    with patch('tools.eval.daemon.scp_from', side_effect=fake_scp):
        assert daemon._pull_latest(REMOTE, run_dir, 'run') == 7

    assert latest.read_bytes() == b'old'
    assert not list(ckpt_dir.glob('.latest.*.pt'))
