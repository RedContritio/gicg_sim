"""Archive extraction tests for ``tools.runs.pull``."""

from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
from pathlib import Path
from unittest.mock import patch

from tools.runs._host import RemoteCfg
from tools.runs.pull import _build_parser, _run_dir, _run_files

_REMOTE = RemoteCfg(ssh='x@y', root='D:/gicg_dev', os='windows', hostname='OTHER-PC')


def _mk_args(tmp_path, **overrides):
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text('')
    args = _build_parser().parse_args([str(cfg), 'stub'])
    for key, value in overrides.items():
        setattr(args, key, value)
    return args


def _make_tar_with_entries(tar_path: Path, entries: dict[str, bytes]):
    with tarfile.open(tar_path, 'w:gz') as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_files_mode_extracts_flat_not_nested(tmp_path):
    run_dir = '202606010000_000149_dmc'
    ckpt_name = 'ckpt_7500.pt'
    ckpt_content = b'fake-checkpoint-data'
    tar_entry = f'{run_dir}/ckpts/{ckpt_name}'
    local_tar = tmp_path / 'transfer.tar.gz'
    _make_tar_with_entries(local_tar, {tar_entry: ckpt_content})

    glob_stdout = f'D:\\gicg_dev\\artifacts\\{run_dir}\\ckpts\\{ckpt_name}\n'
    glob_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=glob_stdout, stderr='')
    tar_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    ssh_call_count = [0]

    def fake_ssh(remote, ps, **kw):
        ssh_call_count[0] += 1
        if 'Get-ChildItem' in ps:
            return glob_result
        if 'tar -czf' in ps:
            return tar_result
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local_dest, **kw):
        shutil.copy2(local_tar, local_dest)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    local_root = tmp_path / 'artifacts'
    local_root.mkdir()
    args = _mk_args(
        tmp_path,
        files=f'artifacts/{run_dir}/ckpts/{ckpt_name}',
        local_root=str(local_root),
    )
    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        rc = _run_files(_REMOTE, args)

    assert rc == 0
    expected = local_root / run_dir / 'ckpts' / ckpt_name
    assert expected.exists(), f'expected {expected} to exist'
    assert expected.read_bytes() == ckpt_content
    nested = local_root / run_dir / 'ckpts' / 'artifacts'
    assert not nested.exists(), f'nested path {nested} must not exist (tar nesting bug)'


def test_dir_mode_extracts_flat_not_nested(tmp_path):
    run_dir = '202606010000_000150_az'
    file_name = 'metrics.jsonl'
    file_content = b'{"step":1}\n'
    tar_entry = f'{run_dir}/{file_name}'
    local_tar = tmp_path / 'transfer.tar.gz'
    _make_tar_with_entries(local_tar, {tar_entry: file_content})

    tar_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_ssh(remote, ps, **kw):
        if 'tar -czf' in ps:
            return tar_result
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local_dest, **kw):
        shutil.copy2(local_tar, local_dest)
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    local_root = tmp_path / 'artifacts'
    local_root.mkdir()
    args = _mk_args(
        tmp_path,
        dir_=f'artifacts/{run_dir}/',
        local_root=str(local_root),
    )
    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull.scp_from', side_effect=fake_scp),
    ):
        rc = _run_dir(_REMOTE, args)

    assert rc == 0
    expected = local_root / run_dir / file_name
    assert expected.exists(), f'expected {expected} to exist'
    assert expected.read_bytes() == file_content
    nested = local_root / 'artifacts'
    assert not nested.exists(), f'nested path {nested} must not exist (tar nesting bug)'


def test_files_mode_tar_cwd_is_artifacts_dir(tmp_path):
    glob_stdout = 'D:\\gicg_dev\\artifacts\\run1\\ckpts\\latest.pt\n'

    def fake_ssh(remote, ps, **kw):
        return subprocess.CompletedProcess(
            args=[], returncode=0, stdout=glob_stdout if 'Get-ChildItem' in ps else '', stderr=''
        )

    args = _mk_args(tmp_path, files='artifacts/run1/ckpts/latest.pt')
    with (
        patch('tools.runs.pull.ssh_run', side_effect=fake_ssh),
        patch('tools.runs.pull._pull_via_tar', return_value=0) as m,
    ):
        _run_files(_REMOTE, args)

    assert m.call_args.args[1] == ['run1/ckpts/latest.pt']
    assert m.call_args.kwargs['tar_cwd'] == 'D:\\gicg_dev\\artifacts'
