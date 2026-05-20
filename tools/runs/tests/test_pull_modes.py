"""Unit tests for ``tools.runs.pull`` — tar+scp transport (no rsync).

All-mock, no ssh / scp. Covers mode mutex, path helpers, legacy ckpt
exclude logic, glob resolve, and PS shape generated for tar pack.
"""

from __future__ import annotations

import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

import pytest

from tools.runs.pull import (
    _build_parser,
    _local_mirror,
    _pull_via_tar,
    _resolve_glob,
    _run_files,
    _run_legacy,
    _to_rel,
    main,
)


def test_parse_run_label():
    args = _build_parser().parse_args(['runlbl'])
    assert args.run_label == 'runlbl'
    assert args.dir_ is None and args.files is None


def test_parse_dir():
    args = _build_parser().parse_args(['--dir', 'artifacts/foo/'])
    assert args.dir_ == 'artifacts/foo/'


def test_parse_files():
    args = _build_parser().parse_args(['--files', '*.toml'])
    assert args.files == '*.toml'


def test_main_mutex_two_modes(capsys):
    with patch('sys.argv', ['pull.py', 'runlbl', '--dir', 'x']):
        assert main() == 2
    assert 'exactly one of' in capsys.readouterr().err


def test_main_mutex_no_mode():
    with patch('sys.argv', ['pull.py']):
        assert main() == 2


def test_to_rel_absolute_in_root():
    assert _to_rel('D:/gicg_dev/artifacts/foo/bar') == 'artifacts/foo/bar'


def test_to_rel_relative():
    assert _to_rel('artifacts/foo') == 'artifacts/foo'


def test_to_rel_absolute_outside_root_raises():
    with pytest.raises(ValueError):
        _to_rel('D:/other/path')


def test_to_rel_backslash_normalized():
    assert _to_rel('D:\\gicg_dev\\artifacts\\foo') == 'artifacts/foo'


def test_local_mirror_artifacts():
    assert _local_mirror('artifacts/run1/perf/', 'artifacts') == Path('artifacts/run1/perf')


def test_local_mirror_non_artifacts_basename():
    assert _local_mirror('other/dir/x', 'artifacts') == Path('artifacts/x')


def _mk_args(**overrides):
    p = _build_parser()
    args = p.parse_args(['stub'])
    for k, v in overrides.items():
        setattr(args, k, v)
    return args


def test_legacy_default_excludes_per_step_ckpts():
    args = _mk_args(run_label='r1', all_ckpts=False)
    with patch('tools.runs.pull._pull_via_tar', return_value=0) as m:
        _run_legacy(args)
    excludes = m.call_args.kwargs.get('excludes', [])
    assert 'ckpts/ckpt_*.pt' in excludes
    assert 'ckpts/gauntlet_*.pt' in excludes


def test_legacy_all_ckpts_no_excludes():
    args = _mk_args(run_label='r1', all_ckpts=True)
    with patch('tools.runs.pull._pull_via_tar', return_value=0) as m:
        _run_legacy(args)
    assert m.call_args.kwargs.get('excludes', []) == []


def test_resolve_glob_empty(capsys):
    args = _mk_args(files='no/match/*.x')
    empty = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with patch('tools.runs.pull.ssh_run', return_value=empty):
        rc = _run_files(args)
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
        rels = _resolve_glob('artifacts/foo/*.toml')
    assert rels == ['artifacts/foo/a.toml', 'artifacts/foo/b.toml']


def test_pull_via_tar_ps_contains_tar_and_cleanup(tmp_path):
    """ssh_run 含 `tar -czf` 主调 + cleanup `Remove-Item` 调。"""
    ps_calls: list[str] = []

    def fake_ssh(ps, **kw):
        ps_calls.append(ps)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(rel, local, **kw):
        with tarfile.open(local, 'w:gz'):
            pass
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        rc = _pull_via_tar(['artifacts/x'], extract_root=tmp_path)
    assert rc == 0
    assert any('tar -czf' in ps for ps in ps_calls)
    assert any('Remove-Item' in ps for ps in ps_calls)
