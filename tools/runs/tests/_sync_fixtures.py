"""Shared fixtures for ``tools.runs.sync`` tests.

Split out so ``test_sync_scan.py`` + ``test_sync_orchestration.py`` can
both reuse the run-dir + SSH-runner builders without duplication.

Metadata bodies are trimmed to **only ``timestamp = "..."``** — that
is the sole field sync reads (T-18 fix-up I-2; full 11-field bodies
were leftover from an earlier draft that planned to pipe through
``schema.load_file``, which never happened).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tools.runs._host import RemoteCfg


REMOTE = RemoteCfg(ssh='u@h', root='/p', os='linux', hostname='remote-host')


@dataclass
class FakeResult:
    returncode: int = 0
    stdout: str = ''
    stderr: str = ''


def mock_runner(captured: list[list[str]], result: FakeResult = FakeResult()):
    """Return a fake ``subprocess.run`` that captures argv into ``captured``."""

    def runner(cmd, **_kw):
        captured.append(list(cmd))
        return result

    return runner


def empty_ssh_runner(_remote, _script, **_kw):
    """SSH find returning empty (no remote runs) — never raises."""
    return FakeResult(returncode=0, stdout='')


def ensure_git_dir(root: Path) -> None:
    """Ensure ``<root>/.git/`` exists so ``_verify_repo_root`` passes."""
    (root / '.git').mkdir(exist_ok=True)


def make_run_dir(root: Path, ts_prefix: str, nnn: str, label: str, timestamp_field: str) -> Path:
    """Create ``<root>/artifacts/<ts_prefix>_<nnn>_<label>/metadata.toml``
    holding **only** the ``timestamp`` field (the sole field sync reads).
    Also ensures ``<root>/.git/`` exists so ``_verify_repo_root`` passes."""
    (root / '.git').mkdir(exist_ok=True)
    run_dir = root / 'artifacts' / f'{ts_prefix}_{nnn}_{label}'
    run_dir.mkdir(parents=True)
    (run_dir / 'metadata.toml').write_text(f'timestamp = "{timestamp_field}"\n')
    return run_dir


def ssh_runner_returning(remote_runs: dict[str, str]):
    """Build an SSH runner emitting the ``===FILE / ===END`` blocks
    expected by ``parse_remote_find_output``. Body holds only the
    ``timestamp`` field per I-2."""

    def runner(_remote, _script, **_kw):
        blocks: list[str] = []
        for nnn, ts in remote_runs.items():
            file_path = f'artifacts/202605180000_{nnn}_remote/metadata.toml'
            body = f'timestamp = "{ts}"\n'
            blocks.append(f'===FILE {file_path}\n{body}\n===END\n')
        return FakeResult(returncode=0, stdout=''.join(blocks))

    return runner
