"""Tests for ``tools.runs.train`` cfg-driven remote dispatch (P3)。

main() now branches on cfg ``[meta].host``:

- ``host == 'local'`` (or absent) → original Phase A → B → C lifecycle
- ``host == 'remote'`` + ``hostname != socket.gethostname()`` →
  ``_dispatch_remote`` (auto-sync + ssh_forward, no local artifacts/<NNN>/)
- ``host == 'remote'`` + ``hostname == socket.gethostname()`` (loopback)
  → fall through to original lifecycle (the remote box running its own
  cfg targeting itself)

All-mock — no real ssh / no real artifacts/ writes for the remote
branch tests; Phase A/B/C mocked out to prove the branch decision in
isolation。 Lifecycle integration coverage lives in
``test_train_main.py`` and ``test_train_dispatch_smoke.py``.
"""

from __future__ import annotations

import socket
import sys
import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.runs import train as train_mod


# ---------------------------------------------------------------------------
# Cfg fixtures — minimal local / remote toml strings written to tmp_path
# ---------------------------------------------------------------------------


def _write_local_cfg(tmp_path: Path) -> Path:
    """meta.host = 'local' (or absent) → original lifecycle path。"""
    p = tmp_path / 'local.toml'
    p.write_text(
        textwrap.dedent(
            """
            [meta]
            seed = 1
            paradigm = "dmc"
            run_label = "local_test"
            host = "local"
            """
        )
    )
    return p


def _write_remote_cfg(tmp_path: Path, hostname: str = 'OTHER-PC') -> Path:
    p = tmp_path / 'remote.toml'
    p.write_text(
        textwrap.dedent(
            f"""
            [meta]
            seed = 1
            paradigm = "dmc"
            run_label = "remote_test"
            host = "remote"
            [remote]
            ssh = "dev@host"
            root = "D:/gicg_dev"
            os = "windows"
            hostname = "{hostname}"
            """
        )
    )
    return p


# ---------------------------------------------------------------------------
# Branch decision — local / loopback fall through to original lifecycle
# ---------------------------------------------------------------------------


def test_local_cfg_runs_lifecycle(tmp_path: Path):
    """meta.host='local' → Phase A called, _dispatch_remote not called。"""
    cfg = _write_local_cfg(tmp_path)

    fake_state = MagicMock()
    with (
        patch.object(train_mod, '_phase_a_setup', return_value=fake_state) as m_setup,
        patch.object(train_mod, '_phase_b_write_cfg_metadata') as m_b,
        patch.object(train_mod, '_phase_c_run_train_and_close', return_value=0) as m_c,
        patch.object(train_mod, '_dispatch_remote') as m_remote,
    ):
        rc = train_mod.main([str(cfg)])
    assert rc == 0
    m_setup.assert_called_once()
    m_b.assert_called_once()
    m_c.assert_called_once()
    m_remote.assert_not_called()


def test_loopback_runs_lifecycle(tmp_path: Path):
    """meta.host='remote' but remote.hostname = our gethostname() → still
    local lifecycle (we ARE the remote box)。"""
    cfg = _write_remote_cfg(tmp_path, hostname=socket.gethostname())

    fake_state = MagicMock()
    with (
        patch.object(train_mod, '_phase_a_setup', return_value=fake_state) as m_setup,
        patch.object(train_mod, '_phase_b_write_cfg_metadata'),
        patch.object(train_mod, '_phase_c_run_train_and_close', return_value=0) as m_c,
        patch.object(train_mod, '_dispatch_remote') as m_remote,
    ):
        rc = train_mod.main([str(cfg)])
    assert rc == 0
    m_setup.assert_called_once()
    m_c.assert_called_once()
    m_remote.assert_not_called()


def test_remote_cfg_dispatches_remote(tmp_path: Path):
    """meta.host='remote' + non-loopback hostname → _dispatch_remote called,
    Phase A/B/C skipped。"""
    cfg = _write_remote_cfg(tmp_path)

    with (
        patch.object(train_mod, '_phase_a_setup') as m_setup,
        patch.object(train_mod, '_phase_b_write_cfg_metadata') as m_b,
        patch.object(train_mod, '_phase_c_run_train_and_close') as m_c,
        patch.object(train_mod, '_dispatch_remote', return_value=0) as m_remote,
    ):
        rc = train_mod.main([str(cfg)])
    assert rc == 0
    m_remote.assert_called_once()
    m_setup.assert_not_called()
    m_b.assert_not_called()
    m_c.assert_not_called()


# ---------------------------------------------------------------------------
# _dispatch_remote internals
# ---------------------------------------------------------------------------


def test_dispatch_remote_sync_fail_aborts(tmp_path: Path):
    """auto-sync subprocess returns non-zero → ssh_forward NOT called,
    main returns sync rc unchanged。"""
    cfg = _write_remote_cfg(tmp_path)

    # subprocess.run mock for the sync step.
    sync_result = MagicMock(returncode=7)
    with (
        patch.object(train_mod.subprocess, 'run', return_value=sync_result) as m_run,
        patch.object(train_mod, 'ssh_forward') as m_fwd,
    ):
        rc = train_mod.main([str(cfg)])
    assert rc == 7
    m_run.assert_called_once()
    # Verify it tried to run the _remote_sync module.
    sync_argv = m_run.call_args[0][0]
    assert sync_argv[0] == sys.executable
    assert '-m' in sync_argv and 'tools.runs._remote_sync' in sync_argv
    m_fwd.assert_not_called()


def test_dispatch_remote_propagates_override_and_resume(tmp_path: Path):
    """``--override A=1 --override B=2 --resume /p`` → ssh_forward
    extra_args list preserves each token in order。"""
    cfg = _write_remote_cfg(tmp_path)

    sync_ok = MagicMock(returncode=0)
    with (
        patch.object(train_mod.subprocess, 'run', return_value=sync_ok),
        patch.object(train_mod, 'ssh_forward', return_value=0) as m_fwd,
    ):
        rc = train_mod.main(
            [
                str(cfg),
                '--override',
                'a.b=1',
                '--override',
                'c.d=2',
                '--resume',
                'artifacts/x/ckpts/latest.pt',
            ]
        )
    assert rc == 0
    m_fwd.assert_called_once()
    # ssh_forward(remote, 'tools.runs.train', cfg_path, extra, stream=True)
    args, kwargs = m_fwd.call_args
    assert args[1] == 'tools.runs.train'
    assert args[2] == Path(str(cfg))
    extra = args[3]
    assert extra == [
        '--override',
        'a.b=1',
        '--override',
        'c.d=2',
        '--resume',
        'artifacts/x/ckpts/latest.pt',
    ]
    # Long-running train → stream=True default for remote branch.
    assert kwargs.get('stream') is True


def test_dispatch_remote_returns_ssh_exit_code(tmp_path: Path):
    """Remote train exit 42 → main returns 42 (no rewrite, no Phase C
    close-metadata mapping locally — that happened on the remote box)。"""
    cfg = _write_remote_cfg(tmp_path)

    sync_ok = MagicMock(returncode=0)
    with (
        patch.object(train_mod.subprocess, 'run', return_value=sync_ok),
        patch.object(train_mod, 'ssh_forward', return_value=42),
    ):
        rc = train_mod.main([str(cfg)])
    assert rc == 42


def test_dispatch_remote_empty_override_passes_clean_extra(tmp_path: Path):
    """No --override / no --resume → extra_args is empty list,
    ssh_forward still gets called with the train module。"""
    cfg = _write_remote_cfg(tmp_path)

    sync_ok = MagicMock(returncode=0)
    with (
        patch.object(train_mod.subprocess, 'run', return_value=sync_ok),
        patch.object(train_mod, 'ssh_forward', return_value=0) as m_fwd,
    ):
        rc = train_mod.main([str(cfg)])
    assert rc == 0
    args, _ = m_fwd.call_args
    assert args[3] == []


def test_dispatch_remote_schema_error_propagates(tmp_path: Path):
    """meta.host='remote' but [remote] section missing → ValueError
    surfaces uncaught (same as other cfg-driven tools)。"""
    bad = tmp_path / 'bad.toml'
    bad.write_text('[meta]\nhost = "remote"\nrun_label = "x"\n')
    with pytest.raises(ValueError, match=r'\[remote\] section missing'):
        train_mod.main([str(bad)])
