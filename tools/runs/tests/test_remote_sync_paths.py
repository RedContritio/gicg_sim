from pathlib import Path
import subprocess
from unittest.mock import patch

from tools.runs._host import RemoteCfg
from tools.runs._remote_sync import (
    _auto_sync,
    _committed_diff,
    _deleted_since_commit,
    _read_remote_sha,
    _tar_and_send,
    _uncommitted_files,
    _uncommitted_deletions,
    _write_remote_sha,
)


def test_sync_preserves_unicode_nested_untracked_and_rename_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def git(*args):
        return subprocess.check_output(['git', *args], text=True).strip()

    git('init', '-q')
    git('config', 'user.name', 'Sync Test')
    git('config', 'user.email', 'sync@example.invalid')
    Path('最好的伙伴.lua').write_text('old')
    Path('tracked file.txt').write_text('original')
    Path('.gitignore').write_text('ignored/\n')
    git('add', '.')
    git('commit', '-qm', 'base')
    base = git('rev-parse', 'HEAD')
    Path('最好的伙伴.lua').rename('最好的伙伴！.lua')
    git('add', '-A')
    Path('tracked file.txt').write_text('modified')
    Path('new folder').mkdir()
    Path('new folder/嵌套.py').write_text('new')
    Path('ignored').mkdir()
    Path('ignored/secret.txt').write_text('ignored')
    Path('.private').write_text('excluded')
    assert set(_uncommitted_files()) == {
        Path('最好的伙伴！.lua'),
        Path('tracked file.txt'),
        Path('new folder/嵌套.py'),
    }
    assert _uncommitted_deletions() == [Path('最好的伙伴.lua')]
    git('add', 'tracked file.txt', 'new folder')
    git('commit', '-qm', 'changes')
    assert Path('最好的伙伴！.lua') in _committed_diff(None)
    assert set(_committed_diff(base)) == {
        Path('最好的伙伴！.lua'),
        Path('tracked file.txt'),
        Path('new folder/嵌套.py'),
    }
    assert _deleted_since_commit(base) == [Path('最好的伙伴.lua')]


def test_auto_sync_always_includes_host_registry(monkeypatch):
    remote = RemoteCfg(ssh='dev@host', root='D:/repo', os='windows', hostname='REMOTE')
    sent: list[list[Path]] = []
    monkeypatch.setattr('tools.runs._remote_sync._git', lambda *args: 'a' * 40)
    monkeypatch.setattr('tools.runs._remote_sync._read_remote_sha', lambda remote: 'b' * 40)
    monkeypatch.setattr('tools.runs._remote_sync._committed_diff', lambda base: [])
    monkeypatch.setattr('tools.runs._remote_sync._uncommitted_files', lambda: [])
    monkeypatch.setattr('tools.runs._remote_sync._deleted_since_commit', lambda base: [])
    monkeypatch.setattr('tools.runs._remote_sync._uncommitted_deletions', lambda: [])
    monkeypatch.setattr('tools.runs._remote_sync._write_remote_sha', lambda remote, sha: 0)

    def capture(remote, paths, label):
        sent.append(list(paths))
        return 0

    monkeypatch.setattr('tools.runs._remote_sync._tar_and_send', capture)
    assert _auto_sync(remote, dry_run=False, base_sha_override=None) == 0
    assert sent == [[Path('configs/hosts/hosts.toml')]]


def _remote_posix() -> RemoteCfg:
    return RemoteCfg(ssh='dev@host', root='/srv/repo', os='linux', hostname='remote')


def test_read_remote_sha_posix_uses_bash():
    result = subprocess.CompletedProcess(args=[], returncode=0, stdout='abc123\n', stderr='')
    with patch('tools.runs._remote_sync.ssh_run_bash', return_value=result) as ssh:
        assert _read_remote_sha(_remote_posix()) == 'abc123'
    assert ssh.call_args.args[1] == ('cd /srv/repo && if [ -f .last_synced_sha ]; then cat .last_synced_sha; fi')


def test_write_remote_sha_posix_uses_bash():
    result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with patch('tools.runs._remote_sync.ssh_run_bash', return_value=result) as ssh:
        assert _write_remote_sha(_remote_posix(), 'abc123') == 0
    assert ssh.call_args.args[1] == 'cd /srv/repo && printf "%s" abc123 > .last_synced_sha'


def test_tar_and_send_posix_extracts_with_bash(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('source')
    scp_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    ssh_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with (
        patch('tools.runs._remote_sync.scp_to', return_value=scp_result),
        patch('tools.runs._remote_sync.ssh_run_bash', return_value=ssh_result) as ssh,
        patch('tools.runs._remote_sync.ssh_run') as powershell,
    ):
        assert _tar_and_send(_remote_posix(), [source], 'test') == 0
    script = ssh.call_args.args[1]
    assert script.startswith('cd /srv/repo && { ')
    assert 'tar -xzf sync.tar.gz' in script
    assert 'rm -f -- sync.tar.gz' in script
    powershell.assert_not_called()


def test_tar_and_send_windows_quotes_remote_root(tmp_path):
    source = tmp_path / 'source.txt'
    source.write_text('source')
    remote = RemoteCfg(ssh='dev@host', root="D:/repo's", os='windows', hostname='REMOTE')
    scp_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    ssh_result = subprocess.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with (
        patch('tools.runs._remote_sync.scp_to', return_value=scp_result),
        patch('tools.runs._remote_sync.ssh_run', return_value=ssh_result) as ssh,
    ):
        assert _tar_and_send(remote, [source], 'test') == 0
    script = ssh.call_args.args[1]
    assert script.startswith("cd 'D:\\repo''s'; tar -xzf sync.tar.gz")
