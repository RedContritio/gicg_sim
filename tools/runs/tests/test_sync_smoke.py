"""Smoke tests for tools.runs.sync — rsync is mocked, never actually
invoked (except integration-marked tests at the bottom of this file
which exercise the real binary + ssh)."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

import pytest

from tools.runs import sync


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: str = ''
    stderr: str = ''


def _mock_runner(captured: list[list[str]], result: FakeResult = FakeResult()):
    """Return a fake subprocess.run that captures the argv into the
    list and returns the supplied result."""

    def runner(cmd, capture_output=False, text=False, check=False, **kw):
        captured.append(list(cmd))
        return result

    return runner


def test_build_command_push_shape(tmp_path):
    cmd = sync.build_command('push', 'dev@host:/d/gicg_dev/', root=tmp_path)
    assert cmd[0] == 'rsync'
    # Local arg should be before remote in push.
    local_idx = cmd.index(f'{tmp_path}/')
    remote_idx = cmd.index('dev@host:/d/gicg_dev/')
    assert local_idx < remote_idx


def test_build_command_pull_shape(tmp_path):
    cmd = sync.build_command('pull', 'dev@host:/d/gicg_dev/', root=tmp_path)
    # Remote arg should be before local in pull.
    local_idx = cmd.index(f'{tmp_path}/')
    remote_idx = cmd.index('dev@host:/d/gicg_dev/')
    assert remote_idx < local_idx


def test_build_command_hardcoded_flags(tmp_path):
    """Spec T4 + risk R6: include/exclude flags MUST be present
    verbatim and SHALL NOT be user-overridable."""
    cmd = sync.build_command('push', 'h:/p/', root=tmp_path)
    assert '-av' in cmd
    assert '--update' in cmd
    assert '--include=artifacts/' in cmd
    assert '--include=artifacts/runs/' in cmd
    assert '--include=artifacts/runs/*.toml' in cmd
    assert '--exclude=*' in cmd


def test_build_command_rejects_bad_direction(tmp_path):
    with pytest.raises(ValueError):
        sync.build_command('sideways', 'h:/p/', root=tmp_path)


def test_build_command_rejects_no_colon():
    with pytest.raises(ValueError, match='colon'):
        sync.build_command('push', 'no-colon-remote')


def test_build_command_rejects_path_without_trailing_slash():
    with pytest.raises(ValueError, match='end with'):
        sync.build_command('push', 'dev@host:/d/gicg_dev')


def test_sync_pull_invokes_rsync_with_expected_argv(tmp_path):
    captured: list[list[str]] = []
    rc = sync.sync(
        direction='pull',
        remote='dev@host:/repo/',
        root=tmp_path,
        runner=_mock_runner(captured),
    )
    assert rc == 0
    assert len(captured) == 1
    cmd = captured[0]
    assert cmd[0] == 'rsync'
    assert 'dev@host:/repo/' in cmd
    assert f'{tmp_path}/' in cmd
    # destination dir must exist after sync (rsync precondition).
    assert (tmp_path / 'artifacts' / 'runs').exists()


def test_sync_push_invokes_rsync_with_expected_argv(tmp_path):
    captured: list[list[str]] = []
    rc = sync.sync(
        direction='push',
        remote='dev@host:/repo/',
        root=tmp_path,
        runner=_mock_runner(captured),
    )
    assert rc == 0
    assert len(captured) == 1


def test_sync_propagates_rsync_failure(tmp_path):
    captured: list[list[str]] = []
    fail = FakeResult(returncode=23, stderr='rsync: receiver failed')
    runner = _mock_runner(captured, fail)
    with pytest.raises(RuntimeError, match='exit 23'):
        sync.sync(
            direction='pull',
            remote='dev@host:/repo/',
            root=tmp_path,
            runner=runner,
        )


def test_sync_handles_missing_rsync_binary(tmp_path):
    def runner(*a, **kw):
        raise FileNotFoundError("[Errno 2] No such file or directory: 'rsync'")

    with pytest.raises(RuntimeError, match='rsync not found'):
        sync.sync(
            direction='pull',
            remote='dev@host:/repo/',
            root=tmp_path,
            runner=runner,
        )


def test_sync_cli_main_happy(tmp_path, monkeypatch, capsys):
    """Patch subprocess.run at module level so the CLI path uses mock."""
    captured: list[list[str]] = []
    monkeypatch.setattr(subprocess, 'run', _mock_runner(captured, FakeResult(stdout='sent 5 files\n')))
    rc = sync.main(
        [
            'pull',
            'dev@host:/repo/',
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 0
    assert len(captured) == 1
    assert 'sent 5 files' in capsys.readouterr().out


def test_sync_cli_main_error_bad_remote(tmp_path, capsys):
    rc = sync.main(
        [
            'pull',
            'no-colon',
            '--root',
            str(tmp_path),
        ]
    )
    assert rc == 1
    assert 'tools.runs.sync' in capsys.readouterr().err


def test_sync_never_includes_checkpoints_or_replays(tmp_path):
    """Risk R6 regression guard: ckpt + replays MUST NOT leak into the
    rsync argv."""
    cmd = sync.build_command('push', 'h:/p/', root=tmp_path)
    joined = ' '.join(cmd)
    assert 'checkpoints' not in joined
    assert 'replays' not in joined


def test_sync_forwards_subprocess_flags(tmp_path):
    """L10: sync.sync() must forward capture_output=True, text=True,
    check=False to the underlying runner. If those defaults silently
    drifted (e.g. text=False), stdout would come back as bytes and the
    print branch + stderr formatting would break — caught here."""
    captured_kwargs: list[dict] = []

    def runner(cmd, **kwargs):
        captured_kwargs.append({'cmd': list(cmd), **kwargs})
        return FakeResult()

    rc = sync.sync(
        direction='pull',
        remote='dev@host:/repo/',
        root=tmp_path,
        runner=runner,
    )
    assert rc == 0
    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]['capture_output'] is True
    assert captured_kwargs[0]['text'] is True
    assert captured_kwargs[0]['check'] is False


# --- integration tests (opt-in via `pytest -m integration`) -----------------
#
# Mock tests above verify argv shape but never invoke rsync; they would not
# catch a typo in RSYNC_FLAGS that still parses as valid argv but makes rsync
# transfer the wrong files (or worse, leak ckpt across hosts). The two tests
# below run real rsync — one bypasses `sync.sync()` and tests `RSYNC_FLAGS`
# in a pure local-to-local transfer; the other goes through `sync.sync()` end
# to end via `localhost:` (real SSH + rsync handshake).


@pytest.mark.integration
def test_rsync_live_local_to_local_filters_correctly(tmp_path):
    """Live rsync(本机→本机)— 验证 RSYNC_FLAGS include/exclude pattern
    真实跑通时 *.toml 入 dst、ckpt 不漏出。Bypasses `sync.sync()` 的
    `_validate_remote` (本地路径无 `:`),直接 invoke rsync with our flags."""
    if shutil.which('rsync') is None:
        pytest.skip('rsync not on PATH')

    src = tmp_path / 'src'
    (src / 'artifacts/runs').mkdir(parents=True)
    (src / 'artifacts/runs/r013.toml').write_text('toml-bytes\n')
    (src / 'artifacts/runs/s068.toml').write_text('toml-bytes\n')
    # Sibling ckpt dir that MUST NOT be transferred (risk R6).
    (src / 'artifacts/202605180244_x').mkdir(parents=True)
    (src / 'artifacts/202605180244_x/ckpt_100.pt').write_text('big-ckpt-bytes\n')
    (src / 'artifacts/202605180244_x/metrics.jsonl').write_text('{"step":1}\n')

    dst = tmp_path / 'dst'
    dst.mkdir()

    cmd = ['rsync', *sync.RSYNC_FLAGS, f'{src}/', f'{dst}/']
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, f'rsync failed: {result.stderr}'

    # toml files transferred
    assert (dst / 'artifacts/runs/r013.toml').read_text() == 'toml-bytes\n'
    assert (dst / 'artifacts/runs/s068.toml').read_text() == 'toml-bytes\n'
    # ckpt dir + contents MUST NOT have leaked
    assert not (dst / 'artifacts/202605180244_x').exists()


def _ssh_localhost_available() -> bool:
    """Return True iff `ssh localhost` works without prompt (BatchMode)."""
    if shutil.which('ssh') is None or shutil.which('rsync') is None:
        return False
    try:
        r = subprocess.run(
            ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=2', 'localhost', 'true'],
            capture_output=True,
            text=True,
            timeout=5,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


@pytest.mark.integration
def test_rsync_live_via_ssh_localhost(tmp_path):
    """Live rsync over `localhost:` — closest-to-prod remote test.
    Exercises full `sync.sync()` path (including `_validate_remote` colon
    check) + real SSH handshake + real rsync over SSH. Auto-skips when
    sshd is off or no passwordless key (typical macOS / clean CI)."""
    if not _ssh_localhost_available():
        pytest.skip('ssh localhost not configured (sshd off / no passwordless key)')

    src = tmp_path / 'src'
    (src / 'artifacts/runs').mkdir(parents=True)
    (src / 'artifacts/runs/r013.toml').write_text('toml-bytes\n')
    (src / 'artifacts/x_ckpts').mkdir(parents=True)
    (src / 'artifacts/x_ckpts/ckpt.pt').write_text('big-bytes\n')

    dst = tmp_path / 'dst'
    dst.mkdir()

    rc = sync.sync(
        direction='push',
        remote=f'localhost:{dst}/',
        root=src,
    )
    assert rc == 0
    assert (dst / 'artifacts/runs/r013.toml').exists()
    # ckpt MUST NOT have leaked across SSH
    assert not (dst / 'artifacts/x_ckpts').exists()


@pytest.mark.integration
def test_rsync_update_tie_mtime_keeps_dst(tmp_path):
    """L5: rsync `--update` flag — equal mtime tie → dst content
    preserved (rsync default). If this behavior flips in a future
    rsync version, our T4 cross-host conflict policy needs revisit."""
    if shutil.which('rsync') is None:
        pytest.skip('rsync not on PATH')

    import os

    src = tmp_path / 'src'
    (src / 'artifacts/runs').mkdir(parents=True)
    (src / 'artifacts/runs/r013.toml').write_text('src-bytes\n')
    dst = tmp_path / 'dst'
    (dst / 'artifacts/runs').mkdir(parents=True)
    (dst / 'artifacts/runs/r013.toml').write_text('dst-bytes\n')

    fixed_mtime = 1700000000.0
    os.utime(src / 'artifacts/runs/r013.toml', (fixed_mtime, fixed_mtime))
    os.utime(dst / 'artifacts/runs/r013.toml', (fixed_mtime, fixed_mtime))

    cmd = ['rsync', *sync.RSYNC_FLAGS, f'{src}/', f'{dst}/']
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert (dst / 'artifacts/runs/r013.toml').read_text() == 'dst-bytes\n'
