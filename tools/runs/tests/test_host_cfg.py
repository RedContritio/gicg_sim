"""Unit tests for ``tools.runs._host`` — cfg loader + RemoteCfg + dispatch helpers。

All-mock。 Schema-validation tests cover required fields, host enum,
os enum, root-shape constraint; loopback/local dispatch tests lock the
``is_local_host`` contract。
"""

from __future__ import annotations

import socket
import textwrap

import pytest

from tools.runs._host import RemoteCfg, is_local_host, load_remote_from_cfg


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
