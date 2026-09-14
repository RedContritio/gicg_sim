from pathlib import Path
import subprocess

from tools.runs._remote_sync import _committed_diff, _deleted_since_commit, _uncommitted_files, _uncommitted_deletions


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
