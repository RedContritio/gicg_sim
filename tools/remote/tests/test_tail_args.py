"""Unit tests for ``tools.remote.tail`` — argparse + path normalize + PS shape.

All-mock, no ssh. Covers drive-letter detection (case-insensitive),
relative-to-REMOTE_ROOT_POSIX prefix, and ``-Wait`` toggle for follow."""

from __future__ import annotations

import subprocess
import sys
from unittest.mock import patch

import pytest

from tools.remote.tail import _build_parser, _build_ps, _normalize_path, main


def test_parse_lines():
    args = _build_parser().parse_args(['some.log', '--lines', '5'])
    assert args.lines == 5


def test_parse_follow_default_lines():
    args = _build_parser().parse_args(['some.log', '--follow'])
    assert args.follow is True
    assert args.lines == 20


def test_parse_timeout():
    args = _build_parser().parse_args(['some.log', '--timeout', '60'])
    assert args.timeout == 60


def test_parse_no_path_rejected():
    with pytest.raises(SystemExit):
        _build_parser().parse_args([])


def test_normalize_drive_letter_backslash():
    assert _normalize_path('D:\\foo\\bar.log') == 'D:\\foo\\bar.log'


def test_normalize_drive_letter_forward_slash():
    assert _normalize_path('D:/foo/bar.log') == 'D:/foo/bar.log'


def test_normalize_drive_letter_lowercase():
    assert _normalize_path('d:/foo/bar.log') == 'd:/foo/bar.log'


def test_normalize_relative_artifacts():
    assert _normalize_path('artifacts/foo.log') == 'D:/gicg_dev/artifacts/foo.log'


def test_normalize_relative_bare():
    assert _normalize_path('foo.log') == 'D:/gicg_dev/foo.log'


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


def test_main_friendly_msg_on_not_found(capsys):
    """`Cannot find path` PS stderr → friendly 'remote file not found' + exit 1."""
    fake = subprocess.CompletedProcess(args=[], returncode=1, stdout='', stderr='Get-Content : Cannot find path X')
    with patch('tools.remote.tail.ssh_run', return_value=fake):
        with patch.object(sys, 'argv', ['tail.py', 'nonexistent.log']):
            rc = main()
    captured = capsys.readouterr()
    assert rc == 1
    assert 'remote file not found' in captured.err
    assert 'Cannot find path' not in captured.err
