"""Tests for IPv6 remote-URL acceptance in ``tools.runs.sync`` (T-19).

Spec §HIGH-6-B — regex must accept the bracket form
``user@[<ipv6>]:path/`` alongside the hostname / IPv4 form. The
T-18 ``test_remote_url_rejects_ipv6_form`` test was flipped to
``test_remote_url_accepts_ipv6_form`` in ``test_sync_pattern.py``;
this file expands the matrix (canonical IPv6, link-local with zone-
absent variants, global, ULA, ``::`` shortcut) and the explicit
malformed-IPv6 rejection cases.
"""

from __future__ import annotations

import subprocess

import pytest

from tools.runs import sync
from tools.runs._host import RemoteCfg
from tools.runs._helpers.sync_scan import fetch_remote_find_text
from tools.runs.tests._sync_fixtures import REMOTE


# ---------------------------------------------------------------------------
# IPv6 forms that MUST be accepted
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'remote',
    [
        'user@[::1]:/path/',  # loopback
        'user@[::1]:relpath/',  # loopback + relative path
        'root@[::1]:/p/',  # bare ``root`` user
        'user@[fe80::1]:/path/',  # link-local
        'user@[2001:db8::1]:/path/',  # global doc-prefix
        'user@[fd00::1]:/path/',  # ULA
        'user@[0:0:0:0:0:0:0:1]:/p/',  # un-compressed loopback
        'dev@[2001:db8:85a3::8a2e:370:7334]:/d/gicg_dev/',  # real-world style
    ],
)
def test_ipv6_accepted(tmp_path, remote):
    cmd = sync.build_rsync_cmd('push', remote, root=tmp_path)
    assert cmd[0] == 'rsync'
    assert remote in cmd


# ---------------------------------------------------------------------------
# Hostname / IPv4 forms must still pass (regression)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'remote',
    [
        'user@host:/path/',
        'user@host.example.com:/path/',
        'user@1.2.3.4:/path/',
        'user@192.0.2.10:/d/gicg_dev/',
        'user@host:relpath/',
    ],
)
def test_hostname_and_ipv4_still_accepted(tmp_path, remote):
    cmd = sync.build_rsync_cmd('push', remote, root=tmp_path)
    assert cmd[0] == 'rsync'


@pytest.mark.parametrize(
    'remote',
    [
        'host:/path/',
        'host.example.com:/path/',
        '1.2.3.4:/d/gicg_dev/',
        '[::1]:/path/',
    ],
)
def test_bare_host_still_accepted(tmp_path, remote):
    cmd = sync.build_rsync_cmd('push', remote, root=tmp_path)
    assert cmd[0] == 'rsync'


# ---------------------------------------------------------------------------
# Malformed / rejected forms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    'remote',
    [
        'user@:/p/',  # empty host
        'user@[::1:/p/',  # unterminated bracket
        'user@::1]:/p/',  # missing opening bracket
        'user@[]:/p/',  # empty bracket
        'user@[::1]:/p',  # missing trailing slash
        'user@[ghij::1]:/p/',  # non-hex inside bracket
        'user@[::1]/p/',  # missing colon between bracket and path
    ],
)
def test_malformed_ipv6_rejected(tmp_path, remote):
    with pytest.raises(ValueError, match=r'\[user@\]host'):
        sync.build_rsync_cmd('push', remote, root=tmp_path)


# ---------------------------------------------------------------------------
# regex source consistency (sync_conflicts._REMOTE_RE consumes the helper pattern)
# ---------------------------------------------------------------------------


def test_remote_regex_pattern_source_imported_from_helper():
    from tools.runs._helpers import sync_conflicts
    from tools.runs._helpers.sync_extras import REMOTE_RE_PATTERN

    assert sync_conflicts._REMOTE_RE.pattern == REMOTE_RE_PATTERN


def test_remote_regex_pattern_contains_ipv6_alternative():
    from tools.runs._helpers.sync_extras import REMOTE_RE_PATTERN

    # Documented HIGH-6-B alternative — guard against regression that
    # silently drops the IPv6 branch.
    assert r'\[[0-9a-fA-F:]+\]' in REMOTE_RE_PATTERN


# ---------------------------------------------------------------------------
# sync() end-to-end — IPv6 remote routed through to the rsync cmd
# ---------------------------------------------------------------------------


def test_sync_dry_run_with_ipv6_remote(tmp_path):
    from tools.runs.tests._sync_fixtures import empty_ssh_runner, ensure_git_dir

    ensure_git_dir(tmp_path)
    remote = RemoteCfg(ssh='user@[::1]', root='/p', os='linux', hostname='remote-host')
    cmd = sync.sync(
        direction='pull',
        remote=remote,
        root=tmp_path,
        ssh_runner=empty_ssh_runner,
        dry_run=True,
    )
    assert isinstance(cmd, list)
    assert 'user@[::1]:/p/' in cmd


@pytest.mark.parametrize(
    ('remote', 'expected'),
    [
        (RemoteCfg(ssh='user@host', root='/path', os='linux', hostname='remote-host'), 'user@host:/path/'),
        (RemoteCfg(ssh='user@1.2.3.4', root='/path', os='linux', hostname='remote-host'), 'user@1.2.3.4:/path/'),
        (RemoteCfg(ssh='user@[::1]', root='/p', os='linux', hostname='remote-host'), 'user@[::1]:/p/'),
        (
            RemoteCfg(ssh='dev@[2001:db8::1]', root='relpath', os='linux', hostname='remote-host'),
            'dev@[2001:db8::1]:relpath/',
        ),
        (
            RemoteCfg(ssh='user@host', root='D:/gicg_dev', os='windows', hostname='remote-host'),
            'user@host:D:/gicg_dev/',
        ),
    ],
)
def test_remote_endpoint_from_cfg(remote, expected):
    assert sync._remote_endpoint(remote) == expected


def test_build_rsync_cmd_accepts_remote_cfg(tmp_path):
    cmd = sync.build_rsync_cmd('push', REMOTE, root=tmp_path)
    assert 'u@h:/p/' in cmd


def test_fetch_remote_find_text_raises_on_nonzero_exit():
    def failing_runner(_remote, _script, **_kw):
        return subprocess.CompletedProcess(args=[], returncode=255, stdout='', stderr='permission denied')

    with pytest.raises(
        RuntimeError,
        match=r'remote scan failed for user@host \(exit 255\): permission denied',
    ):
        remote = RemoteCfg(ssh='user@host', root='/p', os='linux', hostname='remote-host')
        fetch_remote_find_text(remote, runner=failing_runner)


def test_fetch_remote_find_text_raises_when_ssh_is_missing():
    def missing_runner(_remote, _script, **_kw):
        raise FileNotFoundError('ssh not found')

    with pytest.raises(RuntimeError, match='remote scan failed for user@host: ssh not found'):
        remote = RemoteCfg(ssh='user@host', root='/p', os='linux', hostname='remote-host')
        fetch_remote_find_text(remote, runner=missing_runner)
