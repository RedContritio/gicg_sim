"""Content-addressed sync manifest (A: push-only-changed, D: read-back verify).

09-19 rework of ``tools/runs/_remote_sync._auto_sync``: the remote keeps
``.sync_manifest.json`` = {repo-relative path: sha256} of everything sync
has placed there. Each auto sync hashes local candidates and pushes only
content-changed files, rewrites the manifest, and reads it back for
verification. These tests stub every network boundary (sha/manifest
read+write, tar, delete) and exercise the orchestration end-to-end.
"""

from __future__ import annotations

from pathlib import Path
from unittest import mock

from tools.runs import _remote_sync as rs


class _FakeRemote:
    os = 'posix'
    root = '/tmp/fake-remote'
    root_native = '/tmp/fake-remote'
    ssh = 'fake'


class _StubbedRemote:
    """In-memory remote: sha pointer + manifest + call counters."""

    def __init__(self):
        self.sha = None
        self.manifest: dict[str, str] = {}
        self.tar_calls: list[list[str]] = []
        self.delete_calls: list[list[str]] = []

    def patch(self):
        import contextlib

        stack = contextlib.ExitStack()
        for maker in (
            mock.patch.object(rs, '_read_remote_sha', lambda r: self.sha),
            mock.patch.object(rs, '_write_remote_sha', lambda r, s: (setattr(self, 'sha', s), 0)[1]),
            mock.patch.object(rs, '_read_remote_manifest', lambda r: dict(self.manifest)),
            mock.patch.object(
                rs,
                '_write_remote_manifest',
                lambda r, m: (setattr(self, 'manifest', dict(m)), 0)[1],
            ),
            mock.patch.object(rs, '_tar_and_send', self._fake_tar),
            mock.patch.object(rs, '_ssh_delete_paths', self._fake_delete),
        ):
            stack.enter_context(maker)
        return stack

    def _fake_tar(self, remote, paths, label):
        self.tar_calls.append([str(p) for p in paths])
        return 0

    def _fake_delete(self, remote, paths):
        self.delete_calls.append([str(p) for p in paths])
        for p in paths:
            self.manifest.pop(str(p), None)
        return 0


def test_second_sync_pushes_nothing():
    """Content-addressing: an unchanged tree triggers zero tar pushes on
    the second sync (pre-09-19 behavior re-pushed every dirty file)."""
    stub = _StubbedRemote()
    with stub.patch():
        assert rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0') == 0
        assert len(stub.tar_calls) == 1
        first_push = len(stub.tar_calls[0])
        assert first_push > 50, 'first sync should push the full candidate set'
        # Manifest read-back verification ran and wrote state back:
        assert len(stub.manifest) == first_push

        assert rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0') == 0
        assert len(stub.tar_calls) == 1, 'second sync must push nothing'


def test_changed_file_pushes_alone():
    """Corrupt one remote hash → next sync pushes exactly that file."""
    stub = _StubbedRemote()
    with stub.patch():
        rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0')
        victim = Path('configs/hosts/hosts.toml')
        stub.manifest[str(victim)] = '0' * 64
        assert rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0') == 0
        assert len(stub.tar_calls) == 2
        assert stub.tar_calls[-1] == [str(victim)]


def test_deletion_runs_once():
    """Repeated uncommitted deletions are skipped once the manifest shows
    the path absent (idempotent delete, no per-sync ssh round trips)."""
    stub = _StubbedRemote()
    with stub.patch():
        rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0')
        n_first = len(stub.delete_calls)
        rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0')
        # Second sync: either no delete call at all, or an empty skip list.
        total_deleted_second = sum(len(c) for c in stub.delete_calls[n_first:])
        assert total_deleted_second == 0


def test_unreadable_candidate_fails_without_advancing_sha():
    stub = _StubbedRemote()
    with stub.patch(), mock.patch.object(rs, '_hash_file', return_value=None):
        assert rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override='HEAD~0') == 2
    assert stub.sha is None
    assert stub.tar_calls == []


def test_manifest_noop_advances_clean_sha():
    stub = _StubbedRemote()
    head = 'a' * 40
    path = Path('configs/hosts/hosts.toml')
    digest = rs._hash_file(path)
    stub.manifest[str(path)] = digest
    with (
        stub.patch(),
        mock.patch.object(rs, '_git', return_value=head),
        mock.patch.object(rs, '_committed_diff', return_value=[]),
        mock.patch.object(rs, '_uncommitted_files', return_value=[]),
        mock.patch.object(rs, '_deleted_since_commit', return_value=[]),
        mock.patch.object(rs, '_uncommitted_deletions', return_value=[]),
    ):
        assert rs._auto_sync(_FakeRemote(), dry_run=False, base_sha_override=None) == 0
    assert stub.sha == head
