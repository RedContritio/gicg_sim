"""Unit tests for ``tools.runs.tail`` — argparse + path normalize + cfg dispatch。

All-mock, no ssh。 Covers drive-letter detection(case-insensitive),
relative-to-``remote.root`` prefix, ``-Wait`` toggle for follow,and the
cfg-driven local-vs-remote dispatch。"""

from __future__ import annotations

import socket
import subprocess
import sys
import textwrap
from unittest.mock import patch

import pytest

from tools.runs._host import RemoteCfg
from tools.runs.tail import _build_parser, _build_ps, _normalize_remote_path, main

_REMOTE = RemoteCfg(ssh='x@y', root='D:/gicg_dev', os='windows', hostname='OTHER-PC')


def _mk_args(cfg, *rest):
    return _build_parser().parse_args([str(cfg), *rest])


def test_parse_lines(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, 'some.log', '--lines', '5')
    assert args.lines == 5


def test_parse_follow_default_lines(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, 'some.log', '--follow')
    assert args.follow is True
    assert args.lines == 20


def test_parse_timeout(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, 'some.log', '--timeout', '60')
    assert args.timeout == 60


def test_parse_no_path_rejected(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    with pytest.raises(SystemExit):
        _build_parser().parse_args([str(cfg)])


def test_normalize_drive_letter_backslash():
    assert _normalize_remote_path(_REMOTE, 'D:\\foo\\bar.log') == 'D:\\foo\\bar.log'


def test_normalize_drive_letter_forward_slash():
    assert _normalize_remote_path(_REMOTE, 'D:/foo/bar.log') == 'D:/foo/bar.log'


def test_normalize_drive_letter_lowercase():
    assert _normalize_remote_path(_REMOTE, 'd:/foo/bar.log') == 'd:/foo/bar.log'


def test_normalize_relative_artifacts():
    assert _normalize_remote_path(_REMOTE, 'artifacts/foo.log') == 'D:/gicg_dev/artifacts/foo.log'


def test_normalize_relative_bare():
    assert _normalize_remote_path(_REMOTE, 'foo.log') == 'D:/gicg_dev/foo.log'


def test_normalize_posix_absolute():
    """``/abs`` path passes through unchanged。"""
    assert _normalize_remote_path(_REMOTE, '/etc/passwd') == '/etc/passwd'


def test_ps_non_follow():
    ps = _build_ps('X', lines=5, follow=False)
    assert 'Get-Content' in ps
    assert '-Tail 5' in ps
    assert '-Encoding UTF8' in ps
    assert '-Wait' not in ps


def test_ps_follow():
    ps = _build_ps('X', lines=20, follow=True)
    assert '-Wait' in ps
    assert '-Tail 20' in ps


def test_main_remote_friendly_msg_on_not_found(tmp_path, capsys):
    """`Cannot find path` PS stderr → friendly 'remote file not found' + exit 1。"""
    cfg = tmp_path / 'remote.toml'
    cfg.write_text(
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "D:/gicg_dev"
            os = "windows"
            hostname = "OTHER-PC"
            """
        )
    )
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='Get-Content : Cannot find path X')
    with patch('tools.runs.tail.ssh_run', return_value=fake):
        with patch.object(sys, 'argv', ['tail.py', str(cfg), 'nonexistent.log']):
            rc = main()
    captured = capsys.readouterr()
    assert rc == 1
    assert 'remote file not found' in captured.err
    assert 'Cannot find path' not in captured.err


# ---------------------------------------------------------------------------
# cfg-driven dispatch tests — local / remote-forward / loopback / schema-error
# ---------------------------------------------------------------------------


def test_dispatch_local_cfg_runs_local(tmp_path):
    cfg = tmp_path / 'local.toml'
    cfg.write_text('[meta]\nhost = "local"\n')
    with patch('tools.runs.tail._run_local', return_value=0) as m:
        with patch.object(sys, 'argv', ['tail.py', str(cfg), 'X', '--lines', '3']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_remote_cfg_runs_remote(tmp_path):
    cfg = tmp_path / 'remote.toml'
    cfg.write_text(
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "D:/X"
            os = "windows"
            hostname = "OTHER-PC"
            """
        )
    )
    with patch('tools.runs.tail._run_remote', return_value=0) as m:
        with patch.object(sys, 'argv', ['tail.py', str(cfg), 'X', '--lines', '3']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_loopback_runs_local(tmp_path):
    cfg = tmp_path / 'loop.toml'
    cfg.write_text(
        textwrap.dedent(
            f"""
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "D:/X"
            os = "windows"
            hostname = "{socket.gethostname()}"
            """
        )
    )
    with patch('tools.runs.tail._run_local', return_value=0) as m:
        with patch.object(sys, 'argv', ['tail.py', str(cfg), 'X']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_missing_remote_section_raises(tmp_path):
    cfg = tmp_path / 'bad.toml'
    cfg.write_text('[meta]\nhost = "remote"\n')
    with patch.object(sys, 'argv', ['tail.py', str(cfg), 'X']):
        with pytest.raises(ValueError, match=r'\[remote\] section missing'):
            main()
