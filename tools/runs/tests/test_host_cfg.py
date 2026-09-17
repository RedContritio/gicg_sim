"""Unit tests for ``tools.runs._host`` — RemoteCfg + dispatch helpers。

All-mock。 Loopback/local dispatch tests lock the ``is_local_host`` contract;
registry parsing and validation live in ``test_host_registry.py``。
"""

from __future__ import annotations

import shlex
import socket
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.runs._host import (
    VENV_DIRS,
    RemoteCfg,
    _venv_python_candidates,
    discover_remote_binary,
    discover_remote_python,
    is_local_host,
    scp_from,
    ssh_run_bash,
)


# ---------------------------------------------------------------------------
# is_local_host — loopback semantics
# ---------------------------------------------------------------------------


def test_is_local_host_none():
    assert is_local_host(None) is True


def test_is_local_host_different_hostname():
    r = RemoteCfg(ssh='x@y', root='/r', os='linux', hostname='OTHER-NEVER-MATCH-PC')
    assert is_local_host(r) is False


def test_is_local_host_loopback():
    r = RemoteCfg(ssh='x@y', root='/r', os='linux', hostname=socket.gethostname())
    assert is_local_host(r) is True


# ---------------------------------------------------------------------------
# RemoteCfg.root_native
# ---------------------------------------------------------------------------


def test_root_native_windows_uses_backslash():
    r = RemoteCfg(ssh='x@y', root='D:/X/Y', os='windows', hostname='h')
    assert r.root_native == 'D:\\X\\Y'


def test_root_native_posix_keeps_forward_slash():
    r = RemoteCfg(ssh='x@y', root='/srv/gicg', os='linux', hostname='h')
    assert r.root_native == '/srv/gicg'


# ---------------------------------------------------------------------------
# ssh_run_bash
# ---------------------------------------------------------------------------


def test_ssh_run_bash_quotes_script_for_remote_shell():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    with patch('tools.runs._host.subprocess.run', return_value=_cp()) as run:
        ssh_run_bash(r, 'mkdir -p "/tmp/a b"')
    assert run.call_args.args[0] == ['ssh', 'u@h', 'bash -c \'mkdir -p "/tmp/a b"\'']


# ---------------------------------------------------------------------------
# scp_from
# ---------------------------------------------------------------------------


def test_scp_from_omits_preserve_by_default():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    with patch('tools.runs._host.subprocess.run', return_value=_cp()) as run:
        scp_from(r, 'artifacts/run/ckpts/latest.pt', Path('/tmp/latest.pt'))
    assert run.call_args.args[0] == ['scp', '-q', 'u@h:/srv/gicg/artifacts/run/ckpts/latest.pt', '/tmp/latest.pt']


def test_scp_from_adds_preserve_when_requested():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    with patch('tools.runs._host.subprocess.run', return_value=_cp()) as run:
        scp_from(r, 'artifacts/run/ckpts/latest.pt', Path('/tmp/latest.pt'), preserve=True)
    assert run.call_args.args[0] == [
        'scp',
        '-q',
        '-p',
        'u@h:/srv/gicg/artifacts/run/ckpts/latest.pt',
        '/tmp/latest.pt',
    ]


# ---------------------------------------------------------------------------
# _venv_python_candidates — grid shape + ordering
# ---------------------------------------------------------------------------


def _cp(stdout: str = '', stderr: str = '', rc: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def test_venv_candidates_windows_full_grid():
    """4 venv dirs × 2 interp sub-paths → 8 candidates。Ordering:
    outer = venv dir,inner = interp subpath。"""
    r = RemoteCfg(ssh='x@y', root='D:/gicg_dev', os='windows', hostname='h')
    cands = _venv_python_candidates(r)
    assert len(cands) == len(VENV_DIRS) * 2  # 4 × 2 = 8
    # First slot = first venv name + first sub-path.
    assert cands[0] == 'D:/gicg_dev/.venv/Scripts/python.exe'
    assert cands[1] == 'D:/gicg_dev/.venv/Scripts/python3.exe'
    assert cands[2] == 'D:/gicg_dev/venv/Scripts/python.exe'
    # Last slot = last venv name + last sub-path.
    assert cands[-1] == 'D:/gicg_dev/.virtualenv/Scripts/python3.exe'
    # All windows candidates use Scripts/python(3).exe.
    for c in cands:
        assert '/Scripts/python' in c and c.endswith('.exe')


def test_venv_candidates_posix_full_grid():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    cands = _venv_python_candidates(r)
    assert len(cands) == len(VENV_DIRS) * 2  # 4 × 2 = 8
    assert cands[0] == '/srv/gicg/.venv/bin/python'
    assert cands[1] == '/srv/gicg/.venv/bin/python3'
    assert cands[-1] == '/srv/gicg/.virtualenv/bin/python3'
    for c in cands:
        assert '/bin/python' in c and not c.endswith('.exe')


def test_venv_candidates_darwin_uses_posix_layout():
    r = RemoteCfg(ssh='u@h', root='/Users/x/gicg', os='darwin', hostname='h')
    cands = _venv_python_candidates(r)
    assert all('/bin/python' in c for c in cands)


# ---------------------------------------------------------------------------
# discover_remote_python — mock the probe
# ---------------------------------------------------------------------------


def test_discover_remote_python_windows_returns_first_match():
    r = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='h')
    with patch(
        'tools.runs._host.ssh_run',
        return_value=_cp(stdout='D:/gicg_dev/.venv/Scripts/python.exe\n'),
    ):
        found = discover_remote_python(r)
    assert found == 'D:/gicg_dev/.venv/Scripts/python.exe'


def test_discover_remote_python_windows_empty_raises():
    r = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='h')
    with patch('tools.runs._host.ssh_run', return_value=_cp(stdout='')):
        with pytest.raises(FileNotFoundError, match='No Python venv found'):
            discover_remote_python(r)


def test_discover_remote_python_windows_hint_mentions_setup_command():
    r = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='h')
    with patch('tools.runs._host.ssh_run', return_value=_cp(stdout='   \n')):
        with pytest.raises(FileNotFoundError, match='python -m venv .venv'):
            discover_remote_python(r)


def test_discover_remote_python_posix_returns_first_match():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    with patch(
        'tools.runs._host.ssh_run_bash',
        return_value=_cp(stdout='/srv/gicg/.venv/bin/python\n'),
    ):
        found = discover_remote_python(r)
    assert found == '/srv/gicg/.venv/bin/python'


def test_discover_remote_python_posix_empty_raises():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    with patch('tools.runs._host.ssh_run_bash', return_value=_cp(stdout='')):
        with pytest.raises(FileNotFoundError, match='No Python venv found'):
            discover_remote_python(r)


def test_discover_remote_python_posix_picks_first_when_multiple_lines():
    """``|| echo`` chain may produce multiple matches if the shell evaluates
    past first — defensive: caller picks the head line。"""
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    multi = '/srv/gicg/.venv/bin/python\n/srv/gicg/venv/bin/python\n'
    with patch('tools.runs._host.ssh_run_bash', return_value=_cp(stdout=multi)):
        found = discover_remote_python(r)
    assert found == '/srv/gicg/.venv/bin/python'


def test_discover_remote_python_posix_shell_quotes_candidates():
    root = '/srv/repo $(touch /tmp/nope) `id` "quoted"'
    r = RemoteCfg(ssh='u@h', root=root, os='linux', hostname='h')
    captured: list[str] = []

    def fake_ssh_run_bash(remote, bash, **kwargs):  # noqa: ARG001
        captured.append(bash)
        return _cp(stdout='')

    with patch('tools.runs._host.ssh_run_bash', side_effect=fake_ssh_run_bash):
        with pytest.raises(FileNotFoundError):
            discover_remote_python(r)
    for candidate in _venv_python_candidates(r):
        assert shlex.quote(candidate) in captured[0]


# ---------------------------------------------------------------------------
# discover_remote_binary — go / gcc / etc on remote PATH
# ---------------------------------------------------------------------------


def test_discover_remote_binary_windows_uses_get_command():
    r = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='h')
    captured: list[str] = []

    def fake_ssh_run(remote, ps_script, **kwargs):  # noqa: ARG001
        captured.append(ps_script)
        return _cp(stdout='C:/go/bin/go.exe\n')

    with patch('tools.runs._host.ssh_run', side_effect=fake_ssh_run):
        found = discover_remote_binary(r, 'go')
    assert found == 'C:/go/bin/go.exe'
    assert 'Get-Command go' in captured[0]


def test_discover_remote_binary_posix_uses_command_v():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    captured: list[str] = []

    def fake_ssh_run_bash(remote, bash, **kwargs):  # noqa: ARG001
        captured.append(bash)
        return _cp(stdout='/usr/local/go/bin/go\n')

    with patch('tools.runs._host.ssh_run_bash', side_effect=fake_ssh_run_bash):
        found = discover_remote_binary(r, 'go')
    assert found == '/usr/local/go/bin/go'
    assert 'command -v go' in captured[0]


def test_discover_remote_binary_windows_empty_raises_path_hint():
    r = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='h')
    with patch('tools.runs._host.ssh_run', return_value=_cp(stdout='')):
        with pytest.raises(FileNotFoundError) as ei:
            discover_remote_binary(r, 'go')
    msg = str(ei.value)
    assert '`go` not in PATH' in msg
    assert 'System Environment Variables' in msg


def test_discover_remote_binary_posix_empty_raises_install_hint():
    r = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='h')
    with patch('tools.runs._host.ssh_run_bash', return_value=_cp(stdout='')):
        with pytest.raises(FileNotFoundError) as ei:
            discover_remote_binary(r, 'gcc')
    msg = str(ei.value)
    assert '`gcc` not in PATH' in msg
    assert 'install or fix $PATH' in msg


def test_discover_remote_binary_strips_trailing_newline():
    r = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='h')
    with patch('tools.runs._host.ssh_run', return_value=_cp(stdout='C:/x/gcc.exe\r\n')):
        found = discover_remote_binary(r, 'gcc')
    assert found == 'C:/x/gcc.exe'
