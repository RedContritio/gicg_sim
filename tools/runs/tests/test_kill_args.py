"""Unit tests for ``tools.runs.kill`` — argparse + PS shape + cfg dispatch。

All-mock, no ssh. Locks the mutex group, mode dispatch, the PS snippet
shape,and the cfg-driven local-vs-remote forwarding。"""

from __future__ import annotations

import socket
import sys
import textwrap
from unittest.mock import patch

import pytest

from tools.runs.kill import _build_parser, _build_ps, main


def _mk_args(cfg, *flags):
    return _build_parser().parse_args([str(cfg), *flags])


def test_parse_all(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--all')
    assert args.all is True
    assert args.pid is None
    assert args.match is None


def test_parse_pid(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--pid', '12345')
    assert args.pid == 12345


def test_parse_match(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--match', 'foo')
    assert args.match == 'foo'


def test_parse_dry_run(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--all', '--dry-run')
    assert args.dry_run is True


def test_parse_timeout(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--all', '--timeout', '60')
    assert args.timeout == 60


def test_mutex_all_plus_pid_rejected(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    with pytest.raises(SystemExit):
        _mk_args(cfg, '--all', '--pid', '1')


def test_mutex_no_mode_rejected(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    with pytest.raises(SystemExit):
        _build_parser().parse_args([str(cfg)])


def test_no_cfg_rejected():
    with pytest.raises(SystemExit):
        _build_parser().parse_args(['--all'])


def test_ps_all_real(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--all')
    ps = _build_ps(args)
    assert 'Get-Process python' in ps
    assert 'Stop-Process -Force' in ps
    assert 'remaining python procs' in ps


def test_ps_all_dry_run(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--all', '--dry-run')
    ps = _build_ps(args)
    assert 'Format-Table' in ps
    assert 'Stop-Process' not in ps


def test_ps_pid_real(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--pid', '123')
    ps = _build_ps(args)
    assert 'Stop-Process -Id 123' in ps
    assert 'try' in ps
    assert 'catch' in ps


def test_ps_pid_dry_run(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--pid', '123', '--dry-run')
    ps = _build_ps(args)
    assert 'Get-Process -Id 123' in ps
    assert 'Stop-Process' not in ps


def test_ps_match_pattern(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--match', 'foo')
    ps = _build_ps(args)
    assert "-like '*foo*'" in ps


def test_ps_match_with_space_quoted(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--match', 'ab cd')
    ps = _build_ps(args)
    assert "'*ab cd*'" in ps


# ---------------------------------------------------------------------------
# cfg-driven dispatch tests — local / remote-forward / loopback / schema-error
# ---------------------------------------------------------------------------


def test_dispatch_local_cfg_runs_local(tmp_path):
    cfg = tmp_path / 'local.toml'
    cfg.write_text('[meta]\nhost = "local"\n')
    with patch('tools.runs.kill._run_local', return_value=0) as m:
        with patch.object(sys, 'argv', ['kill.py', str(cfg), '--all', '--dry-run']):
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
    with patch('tools.runs.kill._run_remote', return_value=0) as m:
        with patch.object(sys, 'argv', ['kill.py', str(cfg), '--all']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_loopback_runs_local(tmp_path):
    """meta.host=remote but socket.gethostname() matches → local run。"""
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
    with patch('tools.runs.kill._run_local', return_value=0) as m:
        with patch.object(sys, 'argv', ['kill.py', str(cfg), '--all', '--dry-run']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_missing_remote_section_raises(tmp_path):
    cfg = tmp_path / 'bad.toml'
    cfg.write_text('[meta]\nhost = "remote"\n')
    with patch.object(sys, 'argv', ['kill.py', str(cfg), '--all']):
        with pytest.raises(ValueError, match=r'\[remote\] section missing'):
            main()
