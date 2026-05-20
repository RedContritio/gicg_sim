"""Unit tests for ``tools.runs.kill`` — argparse + PS command generation.

All-mock, no ssh. Locks the mutex group, mode dispatch, and the exact
PowerShell snippet shape so accidental regressions are caught."""

from __future__ import annotations

import pytest

from tools.runs.kill import _build_parser, _build_ps


def test_parse_all():
    args = _build_parser().parse_args(['--all'])
    assert args.all is True
    assert args.pid is None
    assert args.match is None


def test_parse_pid():
    args = _build_parser().parse_args(['--pid', '12345'])
    assert args.pid == 12345


def test_parse_match():
    args = _build_parser().parse_args(['--match', 'foo'])
    assert args.match == 'foo'


def test_parse_dry_run():
    args = _build_parser().parse_args(['--all', '--dry-run'])
    assert args.dry_run is True


def test_parse_timeout():
    args = _build_parser().parse_args(['--all', '--timeout', '60'])
    assert args.timeout == 60


def test_mutex_all_plus_pid_rejected():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(['--all', '--pid', '1'])


def test_mutex_no_mode_rejected():
    with pytest.raises(SystemExit):
        _build_parser().parse_args([])


def test_ps_all_real():
    args = _build_parser().parse_args(['--all'])
    ps = _build_ps(args)
    assert 'Get-Process python' in ps
    assert 'Stop-Process -Force' in ps
    assert 'remaining python procs' in ps


def test_ps_all_dry_run():
    args = _build_parser().parse_args(['--all', '--dry-run'])
    ps = _build_ps(args)
    assert 'Format-Table' in ps
    assert 'Stop-Process' not in ps


def test_ps_pid_real():
    args = _build_parser().parse_args(['--pid', '123'])
    ps = _build_ps(args)
    assert 'Stop-Process -Id 123' in ps
    assert 'try' in ps
    assert 'catch' in ps


def test_ps_pid_dry_run():
    args = _build_parser().parse_args(['--pid', '123', '--dry-run'])
    ps = _build_ps(args)
    assert 'Get-Process -Id 123' in ps
    assert 'Stop-Process' not in ps


def test_ps_match_pattern():
    args = _build_parser().parse_args(['--match', 'foo'])
    ps = _build_ps(args)
    assert "-like '*foo*'" in ps


def test_ps_match_with_space_quoted():
    args = _build_parser().parse_args(['--match', 'ab cd'])
    ps = _build_ps(args)
    assert "'*ab cd*'" in ps
