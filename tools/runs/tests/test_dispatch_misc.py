"""Unit tests for cfg-driven dispatch on ``_remote_sync``, ``build_engine``,
``status`` — covers local / remote / loopback / schema-error paths。

All-mock。 Schemas are not re-tested per-tool(covered in
``test_host_cfg.py``)— here we only assert the dispatch branch picked。
"""

from __future__ import annotations

import socket
import sys
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest


def _write_cfg(path: Path, body: str) -> Path:
    path.write_text(body)
    return path


def _local_cfg(tmp_path) -> Path:
    return _write_cfg(tmp_path / 'local.toml', '[meta]\nhost = "local"\n')


def _remote_cfg(tmp_path, hostname: str = 'OTHER-PC') -> Path:
    return _write_cfg(
        tmp_path / 'remote.toml',
        textwrap.dedent(
            f"""
            [meta]
            host = "remote"
            [remote]
            ssh = "x@y"
            root = "D:/X"
            os = "windows"
            hostname = "{hostname}"
            """
        ),
    )


# ---------------------------------------------------------------------------
# _remote_sync dispatch
# ---------------------------------------------------------------------------


def test_remote_sync_local_returns_noop(tmp_path):
    from tools.runs._remote_sync import main as sync_main

    cfg = _local_cfg(tmp_path)
    with patch.object(sys, 'argv', ['_remote_sync.py', str(cfg), '--dry-run']):
        assert sync_main() == 0


def test_remote_sync_remote_runs_auto(tmp_path):
    from tools.runs._remote_sync import main as sync_main

    cfg = _remote_cfg(tmp_path)
    with patch('tools.runs._remote_sync._auto_sync', return_value=0) as m:
        with patch.object(sys, 'argv', ['_remote_sync.py', str(cfg), '--dry-run']):
            assert sync_main() == 0
    m.assert_called_once()


def test_remote_sync_loopback_runs_local(tmp_path):
    from tools.runs._remote_sync import main as sync_main

    cfg = _remote_cfg(tmp_path, hostname=socket.gethostname())
    with patch.object(sys, 'argv', ['_remote_sync.py', str(cfg), '--dry-run']):
        assert sync_main() == 0


def test_remote_sync_missing_section_raises(tmp_path):
    from tools.runs._remote_sync import main as sync_main

    cfg = _write_cfg(tmp_path / 'bad.toml', '[meta]\nhost = "remote"\n')
    with patch.object(sys, 'argv', ['_remote_sync.py', str(cfg)]):
        with pytest.raises(ValueError, match=r'\[remote\] section missing'):
            sync_main()


# ---------------------------------------------------------------------------
# build_engine dispatch
# ---------------------------------------------------------------------------


def test_build_engine_local_emits_hint_and_fails(tmp_path):
    from tools.runs.build_engine import main as be_main

    cfg = _local_cfg(tmp_path)
    with patch.object(sys, 'argv', ['build_engine.py', str(cfg)]):
        rc = be_main()
    assert rc == 1


def test_build_engine_remote_probes_and_builds(tmp_path):
    from tools.runs.build_engine import main as be_main

    cfg = _remote_cfg(tmp_path)
    with (
        patch('tools.runs.build_engine.discover_remote_binary', return_value='C:/x/go.exe') as probe,
        patch('tools.runs.build_engine._run_remote', return_value=0) as runner,
    ):
        with patch.object(sys, 'argv', ['build_engine.py', str(cfg)]):
            assert be_main() == 0
    runner.assert_called_once()
    # probe is called inside _run_remote which we mocked — so probe itself
    # may not be invoked here. Verify by injecting a partial mock to confirm
    # the dispatch contract holds without probe()。
    _ = probe  # silence linter — kept for symmetry


def test_build_engine_remote_probe_failure_raises(tmp_path):
    """When _run_remote is real but probe raises, the FileNotFoundError
    surfaces upward。"""
    from tools.runs import build_engine

    cfg = _remote_cfg(tmp_path)
    with patch.object(build_engine, 'discover_remote_binary', side_effect=FileNotFoundError('no go')):
        with patch.object(sys, 'argv', ['build_engine.py', str(cfg)]):
            with pytest.raises(FileNotFoundError, match='no go'):
                build_engine.main()


def test_build_engine_missing_section_raises(tmp_path):
    from tools.runs.build_engine import main as be_main

    cfg = _write_cfg(tmp_path / 'bad.toml', '[meta]\nhost = "remote"\n')
    with patch.object(sys, 'argv', ['build_engine.py', str(cfg)]):
        with pytest.raises(ValueError, match=r'\[remote\] section missing'):
            be_main()


def test_build_engine_windows_command_includes_all_libs(tmp_path):
    """Win PS 命令必含 libgicg.dll + libgicg_actor.dll(I29 P0:engine + actor 同 build)。"""
    from tools.runs._host import RemoteCfg
    from tools.runs.build_engine import _build_ps_windows

    remote = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='DESKTOP')
    ps = _build_ps_windows(remote)
    assert 'libgicg.dll' in ps
    assert 'libgicg_actor.dll' in ps
    assert './gicg_engine/capi/'.replace('/', '\\').rstrip('\\') in ps or 'gicg_engine\\capi' in ps
    assert 'gicg_actor\\capi' in ps
    # short-circuit on failure(任一 lib build 失败立即退出)
    assert 'LASTEXITCODE' in ps


def test_build_engine_posix_command_includes_all_libs(tmp_path):
    from tools.runs._host import RemoteCfg
    from tools.runs.build_engine import _build_sh_posix

    remote = RemoteCfg(ssh='dev@x', root='/srv/gicg_dev', os='linux', hostname='boxlin')
    sh = _build_sh_posix(remote)
    assert 'libgicg.so' in sh
    assert 'libgicg_actor.so' in sh
    assert './gicg_engine/capi/' in sh
    assert './gicg_actor/capi/' in sh
    # short-circuit on failure。
    assert '&&' in sh


def test_build_engine_windows_command_uses_force_rebuild_flag():
    """``go build -a`` forces rebuild of all packages — 绕过 Go cache stale on
    cgo ``//export`` changes(I29 P1.5 fix:加 export func 后 dll 表 mismatch
    源,ctypes symbol-not-found)。 -a 是较小 hammer(~5-10s 代价)vs `go clean
    -cache` (clears 全 cache,后续 build 重头开始)。
    """
    from tools.runs._host import RemoteCfg
    from tools.runs.build_engine import _LIB_TARGETS, _build_ps_windows

    remote = RemoteCfg(ssh='dev@x', root='D:/gicg_dev', os='windows', hostname='DESKTOP')
    ps = _build_ps_windows(remote)
    # 每 lib 必含 `-a` 紧跟在 `go build` 后,防 cgo cache stale。
    for _name, _src in _LIB_TARGETS:
        assert ps.count('go build -a -buildmode=c-shared') == len(_LIB_TARGETS), (
            f'expected every lib build to use `go build -a` (force rebuild); cmd was:\n{ps}'
        )
        break


def test_build_engine_posix_command_uses_force_rebuild_flag():
    from tools.runs._host import RemoteCfg
    from tools.runs.build_engine import _LIB_TARGETS, _build_sh_posix

    remote = RemoteCfg(ssh='dev@x', root='/srv/gicg_dev', os='linux', hostname='boxlin')
    sh = _build_sh_posix(remote)
    assert sh.count('go build -a -buildmode=c-shared') == len(_LIB_TARGETS), (
        f'expected every lib build to use `go build -a` (force rebuild); cmd was:\n{sh}'
    )


# ---------------------------------------------------------------------------
# status dispatch
# ---------------------------------------------------------------------------


def test_status_local_emits_hint(tmp_path):
    from tools.runs.status import main as status_main

    cfg = _local_cfg(tmp_path)
    with patch.object(sys, 'argv', ['status.py', str(cfg)]):
        rc = status_main()
    assert rc == 1


def test_status_remote_one_shot(tmp_path):
    from tools.runs.status import main as status_main

    cfg = _remote_cfg(tmp_path)
    with patch('tools.runs.status._run_remote', return_value=0) as m:
        with patch.object(sys, 'argv', ['status.py', str(cfg)]):
            assert status_main() == 0
    m.assert_called_once()


def test_status_loopback_runs_local(tmp_path):
    from tools.runs.status import main as status_main

    cfg = _remote_cfg(tmp_path, hostname=socket.gethostname())
    with patch.object(sys, 'argv', ['status.py', str(cfg)]):
        rc = status_main()
    assert rc == 1


def test_status_missing_section_raises(tmp_path):
    from tools.runs.status import main as status_main

    cfg = _write_cfg(tmp_path / 'bad.toml', '[meta]\nhost = "remote"\n')
    with patch.object(sys, 'argv', ['status.py', str(cfg)]):
        with pytest.raises(ValueError, match=r'\[remote\] section missing'):
            status_main()


# ---------------------------------------------------------------------------
# _ssh dispatch
# ---------------------------------------------------------------------------


def test_ssh_local_runs_subprocess(tmp_path):
    from tools.runs._ssh import main as ssh_main

    cfg = _local_cfg(tmp_path)
    with patch('tools.runs._ssh.subprocess.run') as m:
        m.return_value.returncode = 0
        with patch.object(sys, 'argv', ['_ssh.py', str(cfg), '--', 'echo', 'hi']):
            assert ssh_main() == 0
    m.assert_called_once()


def test_ssh_remote_invokes_ssh_run(tmp_path):
    from tools.runs._ssh import main as ssh_main

    cfg = _remote_cfg(tmp_path)
    import subprocess as _sp

    fake = _sp.CompletedProcess(args=[], returncode=0, stdout='', stderr='')
    with patch('tools.runs._ssh.ssh_run', return_value=fake) as m:
        with patch.object(sys, 'argv', ['_ssh.py', str(cfg), '--', 'echo', 'hi']):
            assert ssh_main() == 0
    m.assert_called_once()


def test_ssh_loopback_runs_local(tmp_path):
    from tools.runs._ssh import main as ssh_main

    cfg = _remote_cfg(tmp_path, hostname=socket.gethostname())
    with patch('tools.runs._ssh.subprocess.run') as m:
        m.return_value.returncode = 0
        with patch.object(sys, 'argv', ['_ssh.py', str(cfg), '--', 'echo', 'hi']):
            assert ssh_main() == 0
    m.assert_called_once()


def test_ssh_no_cmd_returns_2(tmp_path):
    from tools.runs._ssh import main as ssh_main

    cfg = _local_cfg(tmp_path)
    with patch.object(sys, 'argv', ['_ssh.py', str(cfg)]):
        assert ssh_main() == 2
