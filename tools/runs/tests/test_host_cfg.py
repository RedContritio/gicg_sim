"""Unit tests for ``tools.runs._host`` — cfg loader + RemoteCfg + dispatch helpers。

All-mock。 Schema-validation tests cover required fields, host enum,
os enum, root-shape constraint; loopback/local dispatch tests lock the
``is_local_host`` contract。
"""

from __future__ import annotations

import socket
import subprocess
import textwrap
from unittest.mock import patch

import pytest

from tools.runs._host import (
    VENV_DIRS,
    RemoteCfg,
    _venv_python_candidates,
    discover_remote_binary,
    discover_remote_python,
    is_local_host,
    load_remote_from_cfg,
)


def _write(tmp_path, body: str):
    p = tmp_path / 'cfg.toml'
    p.write_text(body)
    return p


# ---------------------------------------------------------------------------
# load_remote_from_cfg — happy paths
# ---------------------------------------------------------------------------


def test_load_local_returns_none(tmp_path):
    cfg = _write(tmp_path, '[meta]\nhost = "local"\n')
    assert load_remote_from_cfg(cfg) is None


def test_load_missing_meta_host_returns_none(tmp_path):
    """``meta.host`` absent default → 'local' → None。"""
    cfg = _write(tmp_path, '[meta]\nparadigm = "dmc"\n')
    assert load_remote_from_cfg(cfg) is None


def test_load_empty_file_returns_none(tmp_path):
    cfg = _write(tmp_path, '')
    assert load_remote_from_cfg(cfg) is None


def test_load_remote_happy_path(tmp_path):
    cfg = _write(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "dev@host"
            root = "D:/gicg_dev"
            os = "windows"
            hostname = "DEV-PC"
            """
        ),
    )
    r = load_remote_from_cfg(cfg)
    assert isinstance(r, RemoteCfg)
    assert r.ssh == 'dev@host'
    assert r.root == 'D:/gicg_dev'
    assert r.os == 'windows'
    assert r.hostname == 'DEV-PC'


def test_load_remote_linux_happy(tmp_path):
    cfg = _write(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "u@h"
            root = "/srv/gicg"
            os = "linux"
            hostname = "lh"
            """
        ),
    )
    r = load_remote_from_cfg(cfg)
    assert r is not None and r.os == 'linux'


# ---------------------------------------------------------------------------
# Sad paths — schema violations all raise ValueError
# ---------------------------------------------------------------------------


def test_load_remote_invalid_host_value(tmp_path):
    cfg = _write(tmp_path, '[meta]\nhost = "wibble"\n')
    with pytest.raises(ValueError, match='host must be'):
        load_remote_from_cfg(cfg)


def test_load_remote_missing_section(tmp_path):
    cfg = _write(tmp_path, '[meta]\nhost = "remote"\n')
    with pytest.raises(ValueError, match=r'\[remote\] section missing'):
        load_remote_from_cfg(cfg)


def test_load_remote_missing_ssh(tmp_path):
    cfg = _write(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            root = "D:/X"
            os = "windows"
            hostname = "H"
            """
        ),
    )
    with pytest.raises(ValueError, match=r"missing required fields \['ssh'\]"):
        load_remote_from_cfg(cfg)


def test_load_remote_missing_multiple(tmp_path):
    cfg = _write(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            """
        ),
    )
    with pytest.raises(ValueError, match='missing required fields'):
        load_remote_from_cfg(cfg)


def test_load_remote_invalid_os(tmp_path):
    cfg = _write(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "/r"
            os = "bsd"
            hostname = "h"
            """
        ),
    )
    with pytest.raises(ValueError, match='os must be'):
        load_remote_from_cfg(cfg)


def test_load_remote_root_backslash_rejected(tmp_path):
    cfg = _write(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "D:\\\\X"
            os = "windows"
            hostname = "h"
            """
        ),
    )
    with pytest.raises(ValueError, match='forward slashes'):
        load_remote_from_cfg(cfg)


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


# ---------------------------------------------------------------------------
# P4 schema strictness — empty ssh / hostname / mixed-separator root all raise
# loudly. Each is a silent-bug surface the P4 audit caught (loopback false-
# positive on empty hostname, scp drive-letter confusion on mixed slash).
# ---------------------------------------------------------------------------


def test_load_remote_empty_ssh_raises(tmp_path):
    bad = tmp_path / 'empty_ssh.toml'
    bad.write_text('[meta]\nhost = "remote"\n[remote]\nssh = ""\nroot = "D:/x"\nos = "windows"\nhostname = "h"\n')
    with pytest.raises(ValueError, match=r'\[remote\]\.ssh must be non-empty'):
        load_remote_from_cfg(bad)


def test_load_remote_empty_hostname_raises(tmp_path):
    bad = tmp_path / 'empty_hostname.toml'
    bad.write_text('[meta]\nhost = "remote"\n[remote]\nssh = "x@y"\nroot = "D:/x"\nos = "windows"\nhostname = ""\n')
    with pytest.raises(ValueError, match=r'\[remote\]\.hostname must be non-empty'):
        load_remote_from_cfg(bad)


def test_load_remote_mixed_slash_root_raises(tmp_path):
    bad = tmp_path / 'mixed_slash.toml'
    bad.write_text(
        '[meta]\nhost = "remote"\n[remote]\nssh = "x@y"\nroot = "D:/foo\\\\bar"\nos = "windows"\nhostname = "h"\n'
    )
    with pytest.raises(ValueError, match=r'forward slashes only, got mixed'):
        load_remote_from_cfg(bad)
