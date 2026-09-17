"""Host registry parsing and cfg profile resolution."""

from __future__ import annotations

from pathlib import Path
import textwrap

import pytest

from tools.runs._host import HOST_REGISTRY, RemoteCfg, load_host_registry, load_remote_from_cfg


def _cfg(tmp_path: Path, body: str) -> Path:
    path = tmp_path / 'cfg.toml'
    path.write_text(textwrap.dedent(body))
    return path


def _registry(tmp_path: Path, body: str) -> Path:
    path = tmp_path / 'hosts.toml'
    path.write_text(textwrap.dedent(body))
    return path


def _remote_cfg(tmp_path: Path, profile: str = 'gpu-win') -> Path:
    return _cfg(
        tmp_path,
        f"""
        [meta]
        host = "remote"
        [remote]
        profile = "{profile}"
        """,
    )


def test_host_registry_default_is_repo_root_relative():
    assert HOST_REGISTRY == Path(__file__).resolve().parents[3] / 'configs/hosts/hosts.toml'


def test_load_host_registry_happy_path(tmp_path):
    path = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = "dev@host"
        root = "D:/gicg_dev"
        os = "windows"
        hostname = "DEV-PC"

        [linux-box]
        ssh = "u@h"
        root = "/srv/gicg"
        os = "linux"
        hostname = "lh"
        """,
    )
    profiles = load_host_registry(path)
    assert set(profiles) == {'gpu-win', 'linux-box'}
    assert profiles['gpu-win'] == RemoteCfg(ssh='dev@host', root='D:/gicg_dev', os='windows', hostname='DEV-PC')
    assert profiles['linux-box'].os == 'linux'


def test_load_remote_happy_path(tmp_path):
    registry = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = "dev@host"
        root = "D:/gicg_dev"
        os = "windows"
        hostname = "DEV-PC"
        """,
    )
    remote = load_remote_from_cfg(_remote_cfg(tmp_path), registry)
    assert remote == RemoteCfg(ssh='dev@host', root='D:/gicg_dev', os='windows', hostname='DEV-PC')


def test_local_cfg_does_not_require_registry(tmp_path):
    cfg = _cfg(tmp_path, '[meta]\nhost = "local"\n')
    assert load_remote_from_cfg(cfg, tmp_path / 'missing.toml') is None


def test_missing_meta_host_defaults_local_without_registry(tmp_path):
    cfg = _cfg(tmp_path, '[meta]\nparadigm = "dmc"\n')
    assert load_remote_from_cfg(cfg, tmp_path / 'missing.toml') is None


def test_empty_cfg_defaults_local_without_registry(tmp_path):
    cfg = _cfg(tmp_path, '')
    assert load_remote_from_cfg(cfg, tmp_path / 'missing.toml') is None


def test_invalid_host_value_raises(tmp_path):
    cfg = _cfg(tmp_path, '[meta]\nhost = "wibble"\n')
    with pytest.raises(ValueError, match='host must be'):
        load_remote_from_cfg(cfg, tmp_path / 'missing.toml')


def test_missing_remote_section_raises(tmp_path):
    cfg = _cfg(tmp_path, '[meta]\nhost = "remote"\n')
    with pytest.raises(ValueError, match=r'\[remote\] section missing'):
        load_remote_from_cfg(cfg, tmp_path / 'missing.toml')


@pytest.mark.parametrize('profile', ['', '   '])
def test_missing_or_empty_profile_raises(tmp_path, profile):
    cfg = _cfg(
        tmp_path,
        f"""
        [meta]
        host = "remote"
        [remote]
        profile = "{profile}"
        """,
    )
    with pytest.raises(ValueError, match=r'\[remote\]\.profile must be non-empty'):
        load_remote_from_cfg(cfg, tmp_path / 'missing.toml')


def test_missing_registry_file_includes_setup_hint(tmp_path):
    with pytest.raises(FileNotFoundError, match='cp configs/hosts/hosts.example.toml configs/hosts/hosts.toml'):
        load_remote_from_cfg(_remote_cfg(tmp_path), tmp_path / 'missing.toml')


def test_unknown_profile_lists_available_profile_names(tmp_path):
    registry = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = "dev@host"
        root = "D:/gicg_dev"
        os = "windows"
        hostname = "DEV-PC"
        """,
    )
    with pytest.raises(ValueError, match='available: gpu-win'):
        load_remote_from_cfg(_remote_cfg(tmp_path, 'missing-profile'), registry)


def test_registry_entry_missing_fields_raises(tmp_path):
    registry = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = "dev@host"
        os = "windows"
        hostname = "DEV-PC"
        """,
    )
    with pytest.raises(ValueError, match=r"missing required fields \['root'\]"):
        load_host_registry(registry)


def test_registry_entry_empty_ssh_raises(tmp_path):
    registry = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = ""
        root = "D:/gicg_dev"
        os = "windows"
        hostname = "DEV-PC"
        """,
    )
    with pytest.raises(ValueError, match='ssh must be non-empty'):
        load_host_registry(registry)


def test_registry_entry_empty_hostname_raises(tmp_path):
    registry = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = "dev@host"
        root = "D:/gicg_dev"
        os = "windows"
        hostname = ""
        """,
    )
    with pytest.raises(ValueError, match='hostname must be non-empty'):
        load_host_registry(registry)


@pytest.mark.parametrize('root', ['', '   '])
def test_registry_entry_empty_root_raises(tmp_path, root):
    registry = _registry(
        tmp_path,
        f"""
        [gpu-win]
        ssh = "dev@host"
        root = "{root}"
        os = "windows"
        hostname = "DEV-PC"
        """,
    )
    with pytest.raises(ValueError, match='root must be non-empty'):
        load_host_registry(registry)


def test_registry_entry_invalid_os_raises(tmp_path):
    registry = _registry(
        tmp_path,
        """
        [gpu-win]
        ssh = "dev@host"
        root = "D:/gicg_dev"
        os = "bsd"
        hostname = "DEV-PC"
        """,
    )
    with pytest.raises(ValueError, match='os must be'):
        load_host_registry(registry)


@pytest.mark.parametrize(
    ('root', 'match'),
    [
        ('D:\\\\gicg_dev', 'forward slashes'),
        ('D:/foo\\\\bar', 'forward slashes only, got mixed'),
    ],
)
def test_registry_entry_invalid_root_separators_raise(tmp_path, root, match):
    registry = _registry(
        tmp_path,
        f"""
        [gpu-win]
        ssh = "dev@host"
        root = "{root}"
        os = "windows"
        hostname = "DEV-PC"
        """,
    )
    with pytest.raises(ValueError, match=match):
        load_host_registry(registry)
