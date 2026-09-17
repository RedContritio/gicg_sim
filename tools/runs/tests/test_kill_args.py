"""Unit tests for ``tools.runs.kill`` — argparse + PS shape + cfg dispatch。

All-mock, no ssh. Locks the mutex group, mode dispatch, the PS snippet
shape,and the cfg-driven local-vs-remote forwarding。"""

from __future__ import annotations

import os
import shlex
import signal
import socket
import subprocess
import sys
import textwrap
from unittest.mock import patch

import pytest

from tools.runs._host import RemoteCfg
from tools.runs.kill import _build_parser, _build_ps, _build_sh, _run_local, _run_remote, main


def _write_registry(tmp_path, hostname: str = 'OTHER-PC'):
    path = tmp_path / 'hosts.toml'
    path.write_text(
        textwrap.dedent(
            f"""
            [test]
            ssh = "x@y"
            root = "D:/X"
            os = "windows"
            hostname = "{hostname}"
            """
        )
    )
    return path


def _remote_cfg(tmp_path, hostname: str = 'OTHER-PC'):
    _write_registry(tmp_path, hostname)
    path = tmp_path / 'remote.toml'
    path.write_text(
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            profile = "test"
            """
        )
    )
    return path


@pytest.fixture(autouse=True)
def _host_registry(tmp_path, monkeypatch):
    monkeypatch.setattr('tools.runs._host.HOST_REGISTRY', tmp_path / 'hosts.toml')


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


@pytest.mark.parametrize('pid', ['0', '-1'])
def test_parse_pid_rejects_non_positive(tmp_path, pid):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    with pytest.raises(SystemExit):
        _mk_args(cfg, '--pid', pid)


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
    assert 'Stop-Process -Id $p.Id -Force -ErrorAction Stop' in ps
    assert 'catch { Write-Error $_ -ErrorAction Continue; $failed=$true }' in ps
    assert '$c=$remaining.Count' in ps
    assert 'if ($failed -or $c -gt 0) { exit 1 } else { exit 0 }' in ps
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


def test_ps_match_real_failure_returns_nonzero(tmp_path):
    cfg = tmp_path / 'c.toml'
    cfg.write_text('')
    args = _mk_args(cfg, '--match', 'worker')
    ps = _build_ps(args)
    assert 'Stop-Process -Id $p.Id -Force -ErrorAction Stop' in ps
    assert 'catch { Write-Error $_ -ErrorAction Continue; $failed=$true }' in ps
    assert '$c=$remaining.Count' in ps
    assert 'if ($failed -or $c -gt 0) { exit 1 } else { exit 0 }' in ps
    assert 'remaining matching procs' in ps


def test_sh_all_dry_run():
    args = _mk_args('/tmp/c.toml', '--all', '--dry-run')
    sh = _build_sh(args)
    assert 'ps -eo pid=,comm=' in sh
    assert 'kill -TERM' not in sh


def test_sh_pid_dry_run():
    args = _mk_args('/tmp/c.toml', '--pid', '123', '--dry-run')
    sh = _build_sh(args)
    assert 'kill -0 123' in sh
    assert 'ps -p 123' in sh
    assert 'kill -TERM' not in sh


def test_sh_pid_real():
    args = _mk_args('/tmp/c.toml', '--pid', '123')
    sh = _build_sh(args)
    assert 'kill -TERM 123' in sh
    assert 'PID 123 still running' in sh
    assert 'exit 1' in sh


def test_sh_match_quotes_pattern():
    pattern = "a'b c"
    args = _mk_args('/tmp/c.toml', '--match', pattern)
    sh = _build_sh(args)
    assert f'-v pat={shlex.quote(pattern)}' in sh


def test_sh_all_exits_zero_when_targets_terminate(tmp_path):
    args = _mk_args('/tmp/c.toml', '--all')
    sh = _build_sh(args)
    child = subprocess.Popen(['sleep', '30'])
    try:
        fake_bin = tmp_path / 'bin'
        fake_bin.mkdir()
        state = tmp_path / 'ps-count'
        fake_ps = fake_bin / 'ps'
        fake_ps.write_text(
            f"""#!/bin/sh
count=0
if [ -f {shlex.quote(str(state))} ]; then count=$(cat {shlex.quote(str(state))}); fi
if [ "$count" -eq 0 ]; then echo "{child.pid} python"; fi
echo $((count + 1)) > {shlex.quote(str(state))}
"""
        )
        fake_ps.chmod(0o755)
        env = os.environ.copy()
        env['PATH'] = f'{fake_bin}:{env["PATH"]}'
        result = subprocess.run(['bash', '-c', sh], capture_output=True, text=True, env=env)
    finally:
        if child.poll() is None:
            child.terminate()
        child.wait(timeout=10)

    assert result.returncode == 0
    assert 'remaining python procs: 0' in result.stdout


def test_remote_posix_uses_bash():
    remote = RemoteCfg(ssh='x@y', root='/srv/gicg', os='linux', hostname='boxlin')
    args = _mk_args('/tmp/c.toml', '--all', '--dry-run')
    fake = subprocess.CompletedProcess(args=[], returncode=0, stdout='123 python3\n', stderr='')
    with patch('tools.runs.kill.ssh_run_bash', return_value=fake) as bash:
        assert _run_remote(remote, args) == 0
    bash.assert_called_once()
    assert bash.call_args.args[1] == _build_sh(args)


def test_remote_posix_propagates_nonzero():
    remote = RemoteCfg(ssh='x@y', root='/srv/gicg', os='linux', hostname='boxlin')
    args = _mk_args('/tmp/c.toml', '--all')
    fake = subprocess.CompletedProcess(args=[], returncode=7, stdout='', stderr='kill failed')
    with patch('tools.runs.kill.ssh_run_bash', return_value=fake):
        assert _run_remote(remote, args) == 7


def test_remote_windows_propagates_nonzero():
    remote = RemoteCfg(ssh='x@y', root='D:/gicg', os='windows', hostname='boxwin')
    args = _mk_args('/tmp/c.toml', '--all')
    fake = subprocess.CompletedProcess(args=[], returncode=7, stdout='', stderr='kill failed')
    with patch('tools.runs.kill.ssh_run', return_value=fake):
        assert _run_remote(remote, args) == 7


def test_run_local_remaining_nonzero_returns_one():
    args = _mk_args('/tmp/c.toml', '--pid', '123')
    with (
        patch('tools.runs.kill._local_pids_matching', return_value=[123]),
        patch('tools.runs.kill.os.kill') as kill,
        patch('tools.runs.kill._pid_exists', return_value=True),
        patch('tools.runs.kill.time.monotonic', side_effect=[0.0, 1.0]),
        patch('tools.runs.kill.KILL_WAIT_SECONDS', 1.0),
    ):
        assert _run_local(args) == 1
    kill.assert_called_once_with(123, signal.SIGTERM)


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
    cfg = _remote_cfg(tmp_path)
    with patch('tools.runs.kill._run_remote', return_value=0) as m:
        with patch.object(sys, 'argv', ['kill.py', str(cfg), '--all']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_loopback_runs_local(tmp_path):
    """meta.host=remote but socket.gethostname() matches → local run。"""
    cfg = _remote_cfg(tmp_path, socket.gethostname())
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
