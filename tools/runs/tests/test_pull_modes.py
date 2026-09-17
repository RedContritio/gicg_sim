"""Unit tests for ``tools.runs.pull`` — tar+scp transport(no rsync)+ cfg dispatch。

All-mock, no ssh / scp. Covers mode mutex, path helpers, legacy ckpt
exclude logic, glob resolve, PS shape for tar pack, + cfg-driven dispatch。
"""

from __future__ import annotations

import re
import socket
import subprocess
import sys
import tarfile
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.runs._host import RemoteCfg
from tools.runs.pull import (
    _build_parser,
    _local_mirror,
    _pull_via_tar,
    _resolve_glob,
    _run_dir,
    _run_files,
    _run_legacy,
    _strip_artifacts_prefix,
    _to_rel,
    main,
)

_REMOTE = RemoteCfg(ssh='x@y', root='D:/gicg_dev', os='windows', hostname='OTHER-PC')
_REMOTE_POSIX = RemoteCfg(ssh='u@h', root='/srv/gicg', os='linux', hostname='OTHER-LINUX')


def _mk_cfg(tmp_path, body: str) -> Path:
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text(body)
    return cfg


def _write_registry(tmp_path, hostname: str = 'OTHER-PC') -> Path:
    path = tmp_path / 'hosts.toml'
    path.write_text(
        textwrap.dedent(
            f"""
            [test]
            ssh = "x@y"
            root = "D:/gicg_dev"
            os = "windows"
            hostname = "{hostname}"
            """
        )
    )
    return path


def _remote_cfg(tmp_path, hostname: str = 'OTHER-PC') -> Path:
    _write_registry(tmp_path, hostname)
    return _mk_cfg(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            profile = "test"
            """
        ),
    )


@pytest.fixture(autouse=True)
def _host_registry(tmp_path, monkeypatch):
    monkeypatch.setattr('tools.runs._host.HOST_REGISTRY', tmp_path / 'hosts.toml')


def test_parse_run_label(tmp_path):
    cfg = _mk_cfg(tmp_path, '')
    args = _build_parser().parse_args([str(cfg), 'runlbl'])
    assert args.run_label == 'runlbl'
    assert args.dir_ is None and args.files is None


def test_parse_dir(tmp_path):
    cfg = _mk_cfg(tmp_path, '')
    args = _build_parser().parse_args([str(cfg), '--dir', 'artifacts/foo/'])
    assert args.dir_ == 'artifacts/foo/'


def test_parse_files(tmp_path):
    cfg = _mk_cfg(tmp_path, '')
    args = _build_parser().parse_args([str(cfg), '--files', '*.toml'])
    assert args.files == '*.toml'


def test_main_mutex_two_modes(tmp_path, capsys):
    cfg = _mk_cfg(tmp_path, '[meta]\nhost = "local"\n')
    with patch.object(sys, 'argv', ['pull.py', str(cfg), 'runlbl', '--dir', 'x']):
        assert main() == 2
    assert 'exactly one of' in capsys.readouterr().err


def test_main_mutex_no_mode(tmp_path):
    cfg = _mk_cfg(tmp_path, '[meta]\nhost = "local"\n')
    with patch.object(sys, 'argv', ['pull.py', str(cfg)]):
        assert main() == 2


def test_to_rel_absolute_in_root():
    assert _to_rel(_REMOTE, 'D:/gicg_dev/artifacts/foo/bar') == 'artifacts/foo/bar'


def test_to_rel_relative():
    assert _to_rel(_REMOTE, 'artifacts/foo') == 'artifacts/foo'


def test_to_rel_absolute_outside_root_raises():
    with pytest.raises(ValueError):
        _to_rel(_REMOTE, 'D:/other/path')


def test_to_rel_backslash_normalized():
    assert _to_rel(_REMOTE, 'D:\\gicg_dev\\artifacts\\foo') == 'artifacts/foo'


def test_to_rel_windows_is_case_insensitive_but_respects_boundary():
    assert _to_rel(_REMOTE, 'D:/GICG_DEV/artifacts/foo') == 'artifacts/foo'
    with pytest.raises(ValueError):
        _to_rel(_REMOTE, 'D:/gicg_dev_extra/artifacts/foo')


def test_to_rel_posix_is_case_sensitive_and_respects_boundary():
    assert _to_rel(_REMOTE_POSIX, '/srv/gicg/artifacts/foo') == 'artifacts/foo'
    with pytest.raises(ValueError):
        _to_rel(_REMOTE_POSIX, '/srv/GICG/artifacts/foo')
    with pytest.raises(ValueError):
        _to_rel(_REMOTE_POSIX, '/srv/gicg_extra/artifacts/foo')


def test_local_mirror_artifacts():
    assert _local_mirror('artifacts/run1/perf/', 'artifacts') == Path('artifacts/run1/perf')


def test_local_mirror_non_artifacts_basename():
    assert _local_mirror('other/dir/x', 'artifacts') == Path('artifacts/x')


def _mk_args(tmp_path, **overrides):
    cfg = _mk_cfg(tmp_path, '')
    p = _build_parser()
    args = p.parse_args([str(cfg), 'stub'])
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def test_legacy_default_excludes_per_step_ckpts(tmp_path):
    args = _mk_args(tmp_path, run_label='r1', all_ckpts=False)
    with patch('tools.runs.pull._pull_via_tar', return_value=0) as m:
        _run_legacy(_REMOTE, args)
    excludes = m.call_args.kwargs.get('excludes', [])
    assert 'ckpts/ckpt_*.pt' in excludes
    assert 'ckpts/gauntlet_*.pt' in excludes


def test_legacy_all_ckpts_no_excludes(tmp_path):
    args = _mk_args(tmp_path, run_label='r1', all_ckpts=True)
    with patch('tools.runs.pull._pull_via_tar', return_value=0) as m:
        _run_legacy(_REMOTE, args)
    assert m.call_args.kwargs.get('excludes', []) == []


def test_resolve_glob_empty(tmp_path, capsys):
    args = _mk_args(tmp_path, files='no/match/*.x')
    empty = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with patch('tools.runs.pull.ssh_run', return_value=empty):
        rc = _run_files(_REMOTE, args)
    assert rc == 1
    assert 'no remote files matched' in capsys.readouterr().err


def test_resolve_glob_returns_relative():
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='D:\\gicg_dev\\artifacts\\foo\\a.toml\nD:\\gicg_dev\\artifacts\\foo\\b.toml\n',
        stderr='',
    )
    with patch('tools.runs.pull.ssh_run', return_value=fake):
        rels = _resolve_glob(_REMOTE, 'artifacts/foo/*.toml')
    assert rels == ['artifacts/foo/a.toml', 'artifacts/foo/b.toml']


def test_resolve_glob_posix_uses_find_pattern():
    fake = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout='/srv/gicg/artifacts/foo/a.toml\n/srv/gicg/artifacts/foo/b.toml\n',
        stderr='',
    )
    with patch('tools.runs.pull.ssh_run_bash', return_value=fake) as ssh:
        rels = _resolve_glob(_REMOTE_POSIX, 'artifacts/foo/*.toml')
    assert rels == ['artifacts/foo/a.toml', 'artifacts/foo/b.toml']
    assert ssh.call_args.args[1] == ("find /srv/gicg -path '/srv/gicg/artifacts/foo/*.toml' -type f -print")


def test_pull_via_tar_ps_contains_tar_and_cleanup(tmp_path):
    """ssh_run 含 `tar -czf` 主调 + cleanup `Remove-Item` 调。"""
    ps_calls: list[str] = []

    def fake_ssh(remote, ps, **kw):
        ps_calls.append(ps)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local, **kw):
        with tarfile.open(local, 'w:gz'):
            pass
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        rc = _pull_via_tar(_REMOTE, ['artifacts/x'], extract_root=tmp_path)
    assert rc == 0
    assert any('tar -czf' in ps for ps in ps_calls)
    assert any('Remove-Item' in ps for ps in ps_calls)


def test_pull_via_tar_posix_uses_bash(tmp_path):
    sh_calls: list[str] = []

    def fake_ssh(remote, script, **kw):
        sh_calls.append(script)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local, **kw):
        with tarfile.open(local, 'w:gz'):
            pass
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    with (
        patch('tools.runs.pull.ssh_run_bash', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        rc = _pull_via_tar(_REMOTE_POSIX, ["run's files"], extract_root=tmp_path)
    assert rc == 0
    assert any('tar -czf' in sh and "'run'\"'\"'s files'" in sh for sh in sh_calls)
    assert any(sh.startswith('rm -f -- ') for sh in sh_calls)


def test_pull_via_tar_windows_quotes_root(tmp_path):
    remote = RemoteCfg(ssh='x@y', root="D:/repo's", os='windows', hostname='OTHER-PC')
    ps_calls: list[str] = []

    def fake_ssh(remote, ps, **kw):
        ps_calls.append(ps)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local, **kw):
        with tarfile.open(local, 'w:gz'):
            pass
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        assert _pull_via_tar(remote, ['artifacts/x'], extract_root=tmp_path) == 0
    assert any(ps.startswith("cd 'D:\\repo''s'; tar -czf") for ps in ps_calls)


def test_pull_via_tar_rejects_empty_path_list(tmp_path, capsys):
    assert _pull_via_tar(_REMOTE, [], extract_root=tmp_path) == 1
    assert 'refusing empty tar path list' in capsys.readouterr().err


def test_dir_mode_remote_root_uses_dot_and_self_excludes_archive(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ps_calls: list[str] = []

    def fake_ssh(remote, ps, **kw):
        ps_calls.append(ps)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local, **kw):
        with tarfile.open(local, 'w:gz'):
            pass
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    args = _mk_args(tmp_path, dir_='D:/gicg_dev')
    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        assert _run_dir(_REMOTE, args) == 0

    tar_command = next(ps for ps in ps_calls if 'tar -czf' in ps)
    match = re.search(r'pull_[0-9a-f]{8}\.tar\.gz', tar_command)
    assert match is not None
    archive = match.group(0)
    assert f"--exclude='{archive}'" in tar_command
    assert f"--exclude='./{archive}'" in tar_command
    assert tar_command.endswith(" '.'")


# ---------------------------------------------------------------------------
# cfg-driven dispatch tests
# ---------------------------------------------------------------------------


def test_dispatch_local_cfg_runs_local_noop(tmp_path):
    cfg = _mk_cfg(tmp_path, '[meta]\nhost = "local"\n')
    with patch.object(sys, 'argv', ['pull.py', str(cfg), 'runlbl']):
        assert main() == 0


def test_dispatch_remote_cfg_runs_legacy(tmp_path):
    cfg = _remote_cfg(tmp_path)
    with patch('tools.runs.pull._run_legacy', return_value=0) as m:
        with patch.object(sys, 'argv', ['pull.py', str(cfg), 'runlbl']):
            assert main() == 0
    m.assert_called_once()


def test_dispatch_loopback_runs_local_noop(tmp_path):
    cfg = _remote_cfg(tmp_path, socket.gethostname())
    with patch.object(sys, 'argv', ['pull.py', str(cfg), 'runlbl']):
        assert main() == 0


def test_dispatch_missing_remote_section_raises(tmp_path):
    cfg = _mk_cfg(tmp_path, '[meta]\nhost = "remote"\n')
    with patch.object(sys, 'argv', ['pull.py', str(cfg), 'runlbl']):
        with pytest.raises(ValueError, match=r'\[remote\] section missing'):
            main()


# ---------------------------------------------------------------------------
# _strip_artifacts_prefix unit tests
# ---------------------------------------------------------------------------


def test_strip_artifacts_prefix_all_under_artifacts():
    paths = ['artifacts/run1/ckpts/ckpt_100.pt', 'artifacts/run1/metrics.jsonl']
    stripped, ok = _strip_artifacts_prefix(paths)
    assert ok is True
    assert stripped == ['run1/ckpts/ckpt_100.pt', 'run1/metrics.jsonl']


def test_strip_artifacts_prefix_none_under_artifacts():
    paths = ['configs/foo.toml', 'data/bar.lua']
    stripped, ok = _strip_artifacts_prefix(paths)
    assert ok is False
    assert stripped == paths  # returned unchanged


def test_strip_artifacts_prefix_mixed_returns_original():
    paths = ['artifacts/run1/x.pt', 'configs/y.toml']
    stripped, ok = _strip_artifacts_prefix(paths)
    assert ok is False
    assert stripped == paths


def test_strip_artifacts_prefix_empty():
    stripped, ok = _strip_artifacts_prefix([])
    assert ok is True
    assert stripped == []
