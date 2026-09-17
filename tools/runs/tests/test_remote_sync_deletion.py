"""I29 follow-up — `_remote_sync` 删除处理:tar-based sync 只能 upsert,
git 删/改名的文件远端永久残留(实际 incident:Win build 撞 stale `capi_init.go`,
手动 `Remove-Item` 才通)。

本测验证:
- `_deleted_since_commit` 用 `git diff --diff-filter=D --name-only` 抓 base..HEAD 间
  的 D 状态(不开 -M 时 rename 也走 D+A,旧路径在 D 集合内 → 旧名能被收)。
- `_uncommitted_deletions` 抓 `git status -s` 的 `D ` / ` D` / `DD` 状态行,与
  `_uncommitted_files`(只收 exists 的)互补。
- `_ssh_delete_paths` Win/POSIX 分支生成正确 ps/sh + ssh 调用。
- `_auto_sync` dry-run 打印删除计划。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from tools.runs._host import RemoteCfg
from tools.runs._remote_sync import (
    _auto_sync,
    _deleted_since_commit,
    _ssh_delete_paths,
    _uncommitted_deletions,
)


def _remote_win() -> RemoteCfg:
    return RemoteCfg(ssh='dev@host', root='D:/repo', os='windows', hostname='REMOTE')


def _remote_posix() -> RemoteCfg:
    return RemoteCfg(ssh='dev@host', root='/srv/repo', os='linux', hostname='remote')


# --- _deleted_since_commit ----------------------------------------------------


def test_deleted_since_commit_first_sync_returns_empty():
    """base=None(首次 sync)→ 无 base 可 diff,返 [](committed_diff 走 ls-files 兜)。"""
    assert _deleted_since_commit(None) == []


def test_deleted_since_commit_calls_git_with_diff_filter_D():
    """命令应为 `git diff --diff-filter=D --name-only <sha>..HEAD`。 必须 D-filter,
    且 **不带 -M** —— 否则 rename 走 R 而非 D+A,旧路径漏。"""
    with patch('tools.runs._remote_sync._git') as g:
        g.return_value = 'gicg_actor/capi_init.go\0tools/runs/foo.py\0'
        out = _deleted_since_commit('abc123')
        g.assert_called_once_with('diff', '--diff-filter=D', '--no-renames', '--name-only', '-z', 'abc123..HEAD')
        assert out == [Path('gicg_actor/capi_init.go'), Path('tools/runs/foo.py')]


def test_deleted_since_commit_filters_empty_lines():
    with patch('tools.runs._remote_sync._git') as g:
        g.return_value = 'a.py\0\0b.py\0'
        assert _deleted_since_commit('sha') == [Path('a.py'), Path('b.py')]


# --- _uncommitted_deletions ---------------------------------------------------


def test_uncommitted_deletions_captures_D_states():
    """HEAD diff includes staged and unstaged deletions as NUL-separated paths."""
    raw = 'staged_del.py\0unstaged_del.py\0both_del.py\0'
    with patch('tools.runs._remote_sync._git') as g:
        g.return_value = raw
        out = _uncommitted_deletions()
        g.assert_called_once_with('diff', 'HEAD', '--diff-filter=D', '--no-renames', '--name-only', '-z')
    assert out == [Path('staged_del.py'), Path('unstaged_del.py'), Path('both_del.py')]


def test_uncommitted_deletions_empty():
    with patch('tools.runs._remote_sync._git') as g:
        g.return_value = ''
        assert _uncommitted_deletions() == []


# --- _ssh_delete_paths --------------------------------------------------------


def test_ssh_delete_paths_empty_skips_ssh():
    """空 list → 直接返 0,不发 ssh(零 IO 优化 + 避免 PowerShell 空数组语法)。"""
    with patch('tools.runs._remote_sync.ssh_run') as ssh:
        rc = _ssh_delete_paths(_remote_win(), [])
        assert rc == 0
        ssh.assert_not_called()


def test_ssh_delete_paths_windows_uses_remove_item_literalpath():
    """Win 路径:PowerShell `Remove-Item -LiteralPath` fail loud,路径用反斜杠。"""
    with patch('tools.runs._remote_sync.ssh_run') as ssh:
        ssh.return_value.returncode = 0
        ssh.return_value.stderr = ''
        rc = _ssh_delete_paths(_remote_win(), [Path('gicg_actor/x.go'), Path('tools/y.py')])
        assert rc == 0
        ps = ssh.call_args[0][1]
    assert 'Remove-Item' in ps
    assert '-LiteralPath' in ps
    assert '-Force' in ps
    assert '-ErrorAction Stop' in ps
    assert 'SilentlyContinue' not in ps
    assert 'if (Test-Path -LiteralPath $path)' in ps
    assert 'exit 0 } catch { Write-Error $_; exit 1 }' in ps
    assert 'gicg_actor\\x.go' in ps
    assert 'tools\\y.py' in ps


def test_ssh_delete_paths_windows_failure_returns_nonzero():
    with patch('tools.runs._remote_sync.ssh_run') as ssh:
        ssh.return_value.returncode = 7
        ssh.return_value.stderr = 'remove failed'
        rc = _ssh_delete_paths(_remote_win(), [Path('stale.py')])
        ps = ssh.call_args[0][1]
    assert rc == 7
    assert 'catch { Write-Error $_; exit 1 }' in ps


def test_ssh_delete_paths_posix_uses_rm_minus_f():
    with patch('tools.runs._remote_sync.ssh_run_bash') as ssh:
        ssh.return_value.returncode = 0
        ssh.return_value.stderr = ''
        rc = _ssh_delete_paths(_remote_posix(), [Path('a.py'), Path('dir/b.py')])
        assert rc == 0
        sh = ssh.call_args[0][1]
    assert 'rm -f' in sh
    assert 'rm -f --' in sh
    assert 'a.py' in sh
    assert 'dir/b.py' in sh


def test_auto_sync_deletion_failure_does_not_advance_sha():
    remote = _remote_win()
    head = 'a' * 40
    with (
        patch('tools.runs._remote_sync._git', return_value=head),
        patch('tools.runs._remote_sync._read_remote_sha', return_value='b' * 40),
        patch('tools.runs._remote_sync._committed_diff', return_value=[]),
        patch('tools.runs._remote_sync._uncommitted_files', return_value=[]),
        patch('tools.runs._remote_sync._deleted_since_commit', return_value=[Path('stale.py')]),
        patch('tools.runs._remote_sync._uncommitted_deletions', return_value=[]),
        patch('tools.runs._remote_sync._tar_and_send', return_value=0),
        patch('tools.runs._remote_sync._ssh_delete_paths', return_value=7) as delete,
        patch('tools.runs._remote_sync._write_remote_sha', return_value=0) as write,
    ):
        assert _auto_sync(remote, dry_run=False, base_sha_override=None) == 7
    delete.assert_called_once_with(remote, [Path('stale.py')])
    write.assert_not_called()


def test_auto_sync_missing_remote_deletion_is_success():
    remote = _remote_win()
    head = 'a' * 40
    with (
        patch('tools.runs._remote_sync._git', return_value=head),
        patch('tools.runs._remote_sync._read_remote_sha', return_value='b' * 40),
        patch('tools.runs._remote_sync._committed_diff', return_value=[]),
        patch('tools.runs._remote_sync._uncommitted_files', return_value=[]),
        patch('tools.runs._remote_sync._deleted_since_commit', return_value=[Path('already-gone.py')]),
        patch('tools.runs._remote_sync._uncommitted_deletions', return_value=[]),
        patch('tools.runs._remote_sync._tar_and_send', return_value=0),
        patch('tools.runs._remote_sync._ssh_delete_paths', return_value=0) as delete,
        patch('tools.runs._remote_sync._write_remote_sha', return_value=0) as write,
    ):
        assert _auto_sync(remote, dry_run=False, base_sha_override=None) == 0
    delete.assert_called_once_with(remote, [Path('already-gone.py')])
    write.assert_called_once_with(remote, head)
