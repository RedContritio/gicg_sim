"""Opt-in POSIX SSH loopback integration tests for tools.runs transports."""

from __future__ import annotations

import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from tools.runs._host import RemoteCfg


def _probe_ssh() -> bool:
    if not shutil.which('ssh'):
        return False
    try:
        proc = subprocess.run(
            [
                'ssh',
                '-o',
                'BatchMode=yes',
                '-o',
                'ConnectTimeout=5',
                'localhost',
                'true',
            ],
            capture_output=True,
            timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def _posix_os() -> str:
    return 'darwin' if sys.platform == 'darwin' else 'linux'


@pytest.fixture
def loopback_env(tmp_path, monkeypatch):
    if not _probe_ssh():
        pytest.skip('ssh localhost not available')
    remote_root = tmp_path / 'remote'
    remote_root.mkdir()
    registry = tmp_path / 'hosts.toml'
    registry.write_text(
        '\n'.join(
            [
                '[loopback]',
                'ssh = "localhost"',
                f'root = "{remote_root}"',
                f'os = "{_posix_os()}"',
                f'hostname = "not-{socket.gethostname()}"',
                '',
            ]
        )
    )
    cfg = tmp_path / 'remote.toml'
    cfg.write_text('[meta]\nhost = "remote"\n[remote]\nprofile = "loopback"\n')
    monkeypatch.setattr('tools.runs._host.HOST_REGISTRY', registry)
    remote = RemoteCfg(
        ssh='localhost',
        root=str(remote_root),
        os=_posix_os(),
        hostname=f'not-{socket.gethostname()}',
    )
    return cfg, remote_root, remote


@pytest.mark.integration
def test_posix_auto_sync_round_trip(loopback_env, tmp_path, monkeypatch, capsys):
    cfg, remote_root, _remote = loopback_env
    repo = tmp_path / 'repo'
    (repo / 'configs' / 'hosts').mkdir(parents=True)
    (repo / 'source.txt').write_text('loopback sync\n')
    (repo / 'configs' / 'hosts' / 'hosts.toml').write_text('[loopback]\nssh = "localhost"\n')
    subprocess.run(['git', 'init', '--quiet'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.email', 'test@example.com'], cwd=repo, check=True)
    subprocess.run(['git', 'config', 'user.name', 'Test'], cwd=repo, check=True)
    subprocess.run(['git', 'add', '.'], cwd=repo, check=True)
    subprocess.run(['git', 'commit', '--quiet', '-m', 'fixture'], cwd=repo, check=True)
    head = subprocess.run(
        ['git', 'rev-parse', 'HEAD'],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()

    monkeypatch.chdir(repo)
    from tools.runs._remote_sync import main as sync_main

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(sys, 'argv', ['_remote_sync.py', str(cfg), '--auto'])
        assert sync_main() == 0

    assert (remote_root / 'source.txt').read_text() == 'loopback sync\n'
    assert (remote_root / '.last_synced_sha').read_text() == head
    assert '[sync]' in capsys.readouterr().out


@pytest.mark.integration
def test_posix_pull_tar_round_trip(loopback_env, tmp_path, monkeypatch):
    cfg, remote_root, _remote = loopback_env
    run_dir = remote_root / 'artifacts' / '20260916220000_000001_dmc'
    (run_dir / 'ckpts').mkdir(parents=True)
    (run_dir / 'metrics.jsonl').write_text('{"kind":"episode","ep":1}\n')
    (run_dir / 'ckpts' / 'ckpt_1.pt').write_bytes(b'checkpoint')
    local_root = tmp_path / 'pulled'

    from tools.runs.pull import main as pull_main

    monkeypatch.setattr(
        sys,
        'argv',
        ['pull.py', str(cfg), '--dir', str(run_dir), '--local-root', str(local_root)],
    )
    assert pull_main() == 0

    pulled = local_root / run_dir.name
    assert (pulled / 'metrics.jsonl').read_text() == '{"kind":"episode","ep":1}\n'
    assert (pulled / 'ckpts' / 'ckpt_1.pt').read_bytes() == b'checkpoint'
    assert not list(remote_root.glob('pull_*.tar.gz'))


@pytest.mark.integration
def test_posix_tail_round_trip(loopback_env, monkeypatch, capsys):
    cfg, remote_root, _remote = loopback_env
    log = remote_root / 'logs' / 'a b.log'
    log.parent.mkdir()
    log.write_text('one\ntwo\nthree\n')

    from tools.runs.tail import main as tail_main

    monkeypatch.setattr(sys, 'argv', ['tail.py', str(cfg), 'logs/a b.log', '--lines', '2'])
    assert tail_main() == 0
    assert capsys.readouterr().out == 'two\nthree\n'


@pytest.mark.integration
def test_posix_kill_pid_dry_run(loopback_env, monkeypatch, capsys):
    cfg, _remote_root, _remote = loopback_env
    child = subprocess.Popen(['sleep', '30'])
    try:
        from tools.runs.kill import main as kill_main

        monkeypatch.setattr(sys, 'argv', ['kill.py', str(cfg), '--pid', str(child.pid), '--dry-run'])
        assert kill_main() == 0
        assert str(child.pid) in capsys.readouterr().out
        assert child.poll() is None
    finally:
        child.terminate()
        child.wait(timeout=10)


@pytest.mark.integration
def test_posix_status_round_trip(loopback_env, monkeypatch, capsys):
    cfg, remote_root, _remote = loopback_env
    run_name = '20260916220000_000001_dmc'
    run_dir = remote_root / 'artifacts' / run_name
    run_dir.mkdir(parents=True)
    (run_dir / 'metrics.jsonl').write_text(
        '{"kind":"episode","ep":1,"frames":10,"wall_s":1.0}\n{"kind":"train_step","step":2,"loss":0.25}\n'
    )

    from tools.runs.status import main as status_main

    monkeypatch.setattr(sys, 'argv', ['status.py', str(cfg), '--run', run_name])
    assert status_main() == 0
    output = capsys.readouterr().out
    assert f'== run: {run_name} ==' in output
    assert 'episode: ep=1 frames=10 wall=1.0s' in output
    assert 'train: step=2 loss=0.250' in output


@pytest.mark.integration
def test_posix_ssh_command_round_trip(loopback_env, monkeypatch, capsys):
    cfg, _remote_root, _remote = loopback_env

    from tools.runs._ssh import main as ssh_main

    monkeypatch.setattr(sys, 'argv', ['_ssh.py', str(cfg), '--', 'printf', 'loopback\\n'])
    assert ssh_main() == 0
    assert 'loopback\n' in capsys.readouterr().out


@pytest.mark.integration
def test_posix_ssh_forward_round_trip(loopback_env, capsys):
    _cfg, remote_root, remote = loopback_env
    (remote_root / 'probe_module.py').write_text('import sys\nprint(repr(sys.argv[1:]))\n')
    venv_bin = remote_root / '.venv' / 'bin'
    venv_bin.mkdir(parents=True)
    (venv_bin / 'python').symlink_to(sys.executable)

    from tools.runs._ssh import ssh_forward

    rc = ssh_forward(remote, 'probe_module', Path('config a.toml'), ['--flag', 'value b'])
    assert rc == 0
    assert "['config a.toml', '--flag', 'value b']" in capsys.readouterr().out
