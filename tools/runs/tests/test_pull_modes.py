"""Unit tests for ``tools.runs.pull`` — tar+scp transport(no rsync)+ cfg dispatch。

All-mock, no ssh / scp. Covers mode mutex, path helpers, legacy ckpt
exclude logic, glob resolve, PS shape for tar pack, + cfg-driven dispatch。
"""

from __future__ import annotations

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


def _mk_cfg(tmp_path, body: str) -> Path:
    cfg = tmp_path / 'cfg.toml'
    cfg.write_text(body)
    return cfg


def _remote_cfg(tmp_path) -> Path:
    return _mk_cfg(
        tmp_path,
        textwrap.dedent(
            """
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "D:/gicg_dev"
            os = "windows"
            hostname = "OTHER-PC"
            """
        ),
    )


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
    cfg = _mk_cfg(
        tmp_path,
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
        ),
    )
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


# ---------------------------------------------------------------------------
# --files extraction path: no nesting (regression test for tar nesting bug)
# ---------------------------------------------------------------------------


def _make_tar_with_entries(tar_path: Path, entries: dict[str, bytes]):
    """Create a real tar.gz with given {arcname: content} entries."""
    import io

    with tarfile.open(tar_path, 'w:gz') as tf:
        for name, data in entries.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_files_mode_extracts_flat_not_nested(tmp_path):
    """--files glob for artifacts/run/ckpts/ckpt_7500.pt must extract to
    artifacts/run/ckpts/ckpt_7500.pt, NOT artifacts/run/ckpts/artifacts/run/ckpts/ckpt_7500.pt.

    Simulates the full _run_files flow with mocked ssh (glob resolve) and
    mocked scp (delivers a tar whose entries match what the remote tar would
    produce after the fix: paths relative to remote artifacts/ dir).
    """
    run_dir = '202606010000_000149_dmc'
    ckpt_name = 'ckpt_7500.pt'
    ckpt_content = b'fake-checkpoint-data'

    # The tar the remote would create: cd <root>/artifacts; tar -czf ... run/ckpts/file
    # After the fix, tar entry is relative to artifacts/ dir.
    tar_entry = f'{run_dir}/ckpts/{ckpt_name}'
    local_tar = tmp_path / 'transfer.tar.gz'
    _make_tar_with_entries(local_tar, {tar_entry: ckpt_content})

    # Mock ssh_run for glob resolve: return absolute Windows paths
    glob_stdout = f'D:\\gicg_dev\\artifacts\\{run_dir}\\ckpts\\{ckpt_name}\n'
    glob_result = subprocess.CompletedProcess(args=[], returncode=0, stdout=glob_stdout, stderr='')

    # Mock ssh_run for tar creation: succeed
    tar_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    ssh_call_count = [0]

    def fake_ssh(remote, ps, **kw):
        ssh_call_count[0] += 1
        if 'Get-ChildItem' in ps:
            return glob_result
        if 'tar -czf' in ps:
            return tar_result
        # cleanup Remove-Item
        return subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')

    def fake_scp(remote, rel, local_dest, **kw):
        import shutil

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

    # Correct: file at artifacts/run/ckpts/ckpt_7500.pt
    expected = local_root / run_dir / 'ckpts' / ckpt_name
    assert expected.exists(), f'expected {expected} to exist'
    assert expected.read_bytes() == ckpt_content

    # Regression: must NOT have nested artifacts/ path
    nested = local_root / run_dir / 'ckpts' / 'artifacts'
    assert not nested.exists(), f'nested path {nested} must not exist (tar nesting bug)'


def test_dir_mode_extracts_flat_not_nested(tmp_path):
    """--dir artifacts/run/ must extract to artifacts/run/, not artifacts/artifacts/run/."""
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
        import shutil

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
    """Verify _run_files passes tar_cwd pointing to remote artifacts/ dir
    (not remote root) so tar entries are artifacts-relative."""
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

    call_kw = m.call_args
    # rel_paths should have artifacts/ prefix stripped
    assert call_kw.args[1] == ['run1/ckpts/latest.pt']
    # tar_cwd should point to remote root + artifacts
    assert call_kw.kwargs['tar_cwd'] == 'D:\\gicg_dev\\artifacts'
