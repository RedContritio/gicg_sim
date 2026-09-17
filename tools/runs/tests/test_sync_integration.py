"""Integration tests for ``tools.runs.sync`` — real rsync subprocess invocation.

Marker: ``@pytest.mark.integration``. Opt-in only; default pytest collection
excludes via ``pyproject.toml`` ``addopts = -m "not smoke_full and not
integration"``. Run with::

    .venv/bin/python -m pytest tools/runs/tests/test_sync_integration.py -v -m integration

Spec ref: ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design-rollout.md``
§测试矩阵 Sync tests.

Two tiers:

1. **Local-to-local** (``test_rsync_flags_filter_*``): invoke ``rsync`` with
   :data:`tools.runs.sync.RSYNC_FLAGS` against two ``tmp_path`` subtrees,
   verify post-transfer dest holds only ``metadata.toml`` + ``cfg_leaf*.toml``
   + ``cfg_resolved*.toml`` and excludes ``ckpts/`` / ``metrics.jsonl`` /
   ``tb/`` / ``.authoritative_host`` / ``.run_id_lock`` / ``.metadata_lock``.
   Skip if ``rsync`` missing on PATH.
2. **SSH-localhost** (``test_sync_ssh_localhost_*``): drive the full
   :func:`tools.runs.sync.sync` orchestration (which runs SSH ``find`` +
   ``rsync`` over ssh) against ``user@localhost:<tmp>/`` and verify the same
   filter contract end-to-end. Skip if ``ssh`` missing OR passwordless
   localhost auth not configured (probed once per test via
   ``ssh -o BatchMode=yes -o ConnectTimeout=2 localhost true``). macOS dev
   boxes typically lack sshd; CI may or may not have it.

Why no mocks here: T-18 / T-19 already cover the orchestration logic with
fake runners (``test_sync_orchestration.py`` etc.). This file's job is to
catch flag drift that mocks can't see — e.g. an rsync version that handles
``--include=*/`` differently, or a typo in :data:`RSYNC_FLAGS` that lets
GB-scale ckpts leak over a slow link.

Timeouts: every subprocess call uses ``timeout=30`` so a hung rsync /
ssh never blocks the suite indefinitely.
"""

from __future__ import annotations

import getpass
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.runs import sync as sync_mod
from tools.runs._host import RemoteCfg

# ---------------------------------------------------------------------------
# Shared fixture builder
# ---------------------------------------------------------------------------


def _build_full_run_tree(src_root: Path, *, nnn: str, label: str, ts_prefix: str, ts_field: str) -> Path:
    """Build one ``<src_root>/artifacts/<ts_prefix>_<nnn>_<label>/`` populated
    with EVERY file kind sync may encounter:

    - ``metadata.toml`` (must transfer)
    - ``cfg_leaf.toml`` + ``cfg_leaf_v2.toml`` (must transfer — both match
      ``cfg_leaf*.toml`` include)
    - ``cfg_resolved.toml`` + ``cfg_resolved_v2.toml`` (must transfer)
    - ``ckpts/ckpt_30.pt`` (must NOT transfer — catch-all ``--exclude=*``)
    - ``metrics.jsonl`` (must NOT transfer)
    - ``tb/events.out`` (must NOT transfer)
    - ``.metadata_lock`` (must NOT transfer — explicit per-run lock exclude)

    Also writes the artifacts-level ``.authoritative_host`` + ``.run_id_lock``
    sentinels (both must NOT transfer — explicit excludes).

    Returns the per-run dir Path for downstream assertions.
    """
    run_dir = src_root / 'artifacts' / f'{ts_prefix}_{nnn}_{label}'
    run_dir.mkdir(parents=True)
    (run_dir / 'metadata.toml').write_text(f'timestamp = "{ts_field}"\n')
    (run_dir / 'cfg_leaf.toml').write_text(f'[meta]\nrun_label = "{label}"\n')
    (run_dir / 'cfg_leaf_v2.toml').write_text(f'[meta]\nrun_label = "{label}"\nv2 = true\n')
    (run_dir / 'cfg_resolved.toml').write_text(f'[meta]\nrun_label = "{label}"\nparadigm = "dmc"\n')
    (run_dir / 'cfg_resolved_v2.toml').write_text(f'[meta]\nrun_label = "{label}"\nv2 = true\n')
    (run_dir / 'ckpts').mkdir()
    (run_dir / 'ckpts' / 'ckpt_30.pt').write_bytes(b'fake ckpt bytes ' * 100)
    (run_dir / 'metrics.jsonl').write_text('{"step": 1}\n{"step": 2}\n')
    (run_dir / 'tb').mkdir()
    (run_dir / 'tb' / 'events.out').write_bytes(b'fake tb event bytes')
    (run_dir / '.metadata_lock').write_text('locked\n')
    (src_root / 'artifacts' / '.authoritative_host').write_text('src-host\n')
    (src_root / 'artifacts' / '.run_id_lock').write_text('')
    return run_dir


def _assert_run_filtered(dst_run: Path) -> None:
    """Post-sync invariant: only metadata + cfg_* transferred for ``dst_run``."""
    assert (dst_run / 'metadata.toml').is_file(), 'metadata.toml must transfer'
    assert (dst_run / 'cfg_leaf.toml').is_file(), 'cfg_leaf.toml must transfer'
    assert (dst_run / 'cfg_leaf_v2.toml').is_file(), 'cfg_leaf_v2.toml must transfer'
    assert (dst_run / 'cfg_resolved.toml').is_file(), 'cfg_resolved.toml must transfer'
    assert (dst_run / 'cfg_resolved_v2.toml').is_file(), 'cfg_resolved_v2.toml must transfer'

    # rsync may create empty ``ckpts/`` / ``tb/`` dirs because the
    # ``--include=artifacts/*/`` rule matches them (then ``--exclude=*``
    # catches their contents). What MUST be true: no files inside.
    if (dst_run / 'ckpts').exists():
        assert not any((dst_run / 'ckpts').iterdir()), 'ckpts/ contents must NOT transfer'
    if (dst_run / 'tb').exists():
        assert not any((dst_run / 'tb').iterdir()), 'tb/ contents must NOT transfer'
    assert not (dst_run / 'metrics.jsonl').exists(), 'metrics.jsonl must NOT transfer'
    assert not (dst_run / '.metadata_lock').exists(), '.metadata_lock must NOT transfer'


def _assert_artifacts_sentinels_filtered(dst_artifacts: Path) -> None:
    """Post-sync invariant: per-host sentinels must NOT cross machines."""
    assert not (dst_artifacts / '.authoritative_host').exists(), (
        '.authoritative_host must NOT transfer (cross-host single-source guard)'
    )
    assert not (dst_artifacts / '.run_id_lock').exists(), '.run_id_lock must NOT transfer (per-host lock)'


# ---------------------------------------------------------------------------
# Tier 1: local-to-local rsync invocation with RSYNC_FLAGS
# ---------------------------------------------------------------------------


@pytest.mark.integration
def test_rsync_flags_filter_single_run_local_to_local(tmp_path):
    """One run dir, full content matrix → only metadata + cfg_*.toml transferred."""
    if not shutil.which('rsync'):
        pytest.skip('rsync not on PATH')
    src_root = tmp_path / 'src'
    dst_root = tmp_path / 'dst'
    (src_root / '.git').mkdir(parents=True)
    (dst_root / '.git').mkdir(parents=True)
    (src_root / 'artifacts').mkdir(parents=True)
    (dst_root / 'artifacts').mkdir(parents=True)
    _build_full_run_tree(
        src_root,
        nnn='000001',
        label='test',
        ts_prefix='202605180400',
        ts_field='2026-05-18T04:00:00Z',
    )

    # Invoke real rsync with the production flag tuple. Trailing slash on
    # source dir = "merge contents", mirroring the ``build_rsync_cmd`` push
    # form (``f'{root}/'``).
    proc = subprocess.run(
        ['rsync', *sync_mod.RSYNC_FLAGS, f'{src_root}/', f'{dst_root}/'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f'rsync failed: stderr={proc.stderr}'

    dst_run = dst_root / 'artifacts' / '202605180400_000001_test'
    assert dst_run.is_dir(), 'run dir must be created'
    _assert_run_filtered(dst_run)
    _assert_artifacts_sentinels_filtered(dst_root / 'artifacts')


@pytest.mark.integration
def test_rsync_flags_filter_multiple_runs_local_to_local(tmp_path):
    """Multiple run dirs in one sync — each independently filtered."""
    if not shutil.which('rsync'):
        pytest.skip('rsync not on PATH')
    src_root = tmp_path / 'src'
    dst_root = tmp_path / 'dst'
    (src_root / '.git').mkdir(parents=True)
    (dst_root / '.git').mkdir(parents=True)
    (src_root / 'artifacts').mkdir(parents=True)
    (dst_root / 'artifacts').mkdir(parents=True)
    _build_full_run_tree(src_root, nnn='000001', label='dmc', ts_prefix='202605180400', ts_field='2026-05-18T04:00:00Z')
    _build_full_run_tree(src_root, nnn='000002', label='az', ts_prefix='202605180500', ts_field='2026-05-18T05:00:00Z')
    _build_full_run_tree(src_root, nnn='000003', label='ppo', ts_prefix='202605180600', ts_field='2026-05-18T06:00:00Z')

    proc = subprocess.run(
        ['rsync', *sync_mod.RSYNC_FLAGS, f'{src_root}/', f'{dst_root}/'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f'rsync failed: stderr={proc.stderr}'

    for nnn, label, ts_prefix in (
        ('000001', 'dmc', '202605180400'),
        ('000002', 'az', '202605180500'),
        ('000003', 'ppo', '202605180600'),
    ):
        _assert_run_filtered(dst_root / 'artifacts' / f'{ts_prefix}_{nnn}_{label}')
    _assert_artifacts_sentinels_filtered(dst_root / 'artifacts')


@pytest.mark.integration
def test_rsync_flags_empty_source_noop_local_to_local(tmp_path):
    """Empty ``artifacts/`` on source → rsync succeeds + dest stays empty."""
    if not shutil.which('rsync'):
        pytest.skip('rsync not on PATH')
    src_root = tmp_path / 'src'
    dst_root = tmp_path / 'dst'
    (src_root / '.git').mkdir(parents=True)
    (src_root / 'artifacts').mkdir(parents=True)
    (dst_root / 'artifacts').mkdir(parents=True)

    proc = subprocess.run(
        ['rsync', *sync_mod.RSYNC_FLAGS, f'{src_root}/', f'{dst_root}/'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f'rsync failed: stderr={proc.stderr}'
    # No run dirs should appear under dst.
    dst_artifacts = dst_root / 'artifacts'
    run_dirs = [p for p in dst_artifacts.iterdir() if p.is_dir()]
    assert run_dirs == [], f'unexpected dirs after empty sync: {run_dirs}'


@pytest.mark.integration
def test_rsync_flags_preserves_stale_dest_run_local_to_local(tmp_path):
    """rsync runs without ``--delete`` → stale dest-only dir must survive sync."""
    if not shutil.which('rsync'):
        pytest.skip('rsync not on PATH')
    src_root = tmp_path / 'src'
    dst_root = tmp_path / 'dst'
    (src_root / 'artifacts').mkdir(parents=True)
    (dst_root / 'artifacts').mkdir(parents=True)
    _build_full_run_tree(src_root, nnn='000001', label='new', ts_prefix='202605180400', ts_field='2026-05-18T04:00:00Z')

    # Pre-existing dest-only run (e.g. older NNN that source archived away).
    stale_run = dst_root / 'artifacts' / '202605180300_000999_old'
    stale_run.mkdir(parents=True)
    (stale_run / 'metadata.toml').write_text('timestamp = "2026-05-18T03:00:00Z"\n')

    proc = subprocess.run(
        ['rsync', *sync_mod.RSYNC_FLAGS, f'{src_root}/', f'{dst_root}/'],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f'rsync failed: stderr={proc.stderr}'

    # Stale run survives — RSYNC_FLAGS deliberately omits ``--delete``.
    assert (stale_run / 'metadata.toml').is_file(), 'stale dest-only run must NOT be deleted'
    # New run still transferred + filtered.
    _assert_run_filtered(dst_root / 'artifacts' / '202605180400_000001_new')


# ---------------------------------------------------------------------------
# Tier 2: SSH-localhost end-to-end via tools.runs.sync.sync()
# ---------------------------------------------------------------------------


def _probe_ssh_localhost() -> bool:
    """Return True iff ``ssh localhost`` works without password prompt.

    Used once per ssh-localhost test as a skip gate. ``BatchMode=yes``
    forbids any interactive prompt (password / known-hosts confirm),
    ``ConnectTimeout=2`` bounds the probe wall time.
    """
    if not shutil.which('ssh'):
        return False
    try:
        proc = subprocess.run(
            [
                'ssh',
                '-o',
                'BatchMode=yes',
                '-o',
                'ConnectTimeout=2',
                '-o',
                'StrictHostKeyChecking=accept-new',
                'localhost',
                'true',
            ],
            capture_output=True,
            timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


@pytest.mark.integration
def test_sync_ssh_localhost_push_filters_correctly(tmp_path):
    """End-to-end ``sync()`` push to ``user@localhost:<tmp>/`` — verifies the
    real SSH find + rsync over ssh path applies the same filter contract."""
    if not shutil.which('rsync'):
        pytest.skip('rsync not on PATH')
    if not _probe_ssh_localhost():
        pytest.skip('ssh localhost not available (no sshd / no passwordless auth)')

    src_root = tmp_path / 'src'
    dst_root = tmp_path / 'dst'
    (src_root / '.git').mkdir(parents=True)
    (dst_root / '.git').mkdir(parents=True)
    (src_root / 'artifacts').mkdir(parents=True)
    (dst_root / 'artifacts').mkdir(parents=True)
    _build_full_run_tree(
        src_root,
        nnn='000001',
        label='ssh',
        ts_prefix='202605180700',
        ts_field='2026-05-18T07:00:00Z',
    )

    # Build remote URL. ``user@localhost:<abs_path>/`` — abs path because
    # remote shell cwd ≠ src_root. getpass.getuser() resolves to the same
    # account ssh BatchMode probed.
    user = getpass.getuser()
    # Use POSIX form for rsync path (Path stringification on POSIX is fine).
    remote = RemoteCfg(ssh=f'{user}@localhost', root=str(dst_root), os='linux', hostname='localhost')

    rc = sync_mod.sync(direction='push', remote=remote, root=src_root)
    assert rc == 0, 'sync() must exit 0'

    dst_run = dst_root / 'artifacts' / '202605180700_000001_ssh'
    assert dst_run.is_dir(), 'run dir must reach dst over ssh'
    _assert_run_filtered(dst_run)
    _assert_artifacts_sentinels_filtered(dst_root / 'artifacts')


@pytest.mark.integration
def test_sync_ssh_localhost_pull_filters_correctly(tmp_path):
    """End-to-end ``sync()`` pull from ``user@localhost:<tmp>/`` — symmetric
    coverage for the pull direction (different rsync argv order)."""
    if not shutil.which('rsync'):
        pytest.skip('rsync not on PATH')
    if not _probe_ssh_localhost():
        pytest.skip('ssh localhost not available (no sshd / no passwordless auth)')

    src_root = tmp_path / 'src'  # "remote" in pull semantics
    dst_root = tmp_path / 'dst'  # local
    (src_root / '.git').mkdir(parents=True)
    (dst_root / '.git').mkdir(parents=True)
    (src_root / 'artifacts').mkdir(parents=True)
    (dst_root / 'artifacts').mkdir(parents=True)
    _build_full_run_tree(
        src_root,
        nnn='000002',
        label='pull',
        ts_prefix='202605180800',
        ts_field='2026-05-18T08:00:00Z',
    )

    user = getpass.getuser()
    remote = RemoteCfg(ssh=f'{user}@localhost', root=str(src_root), os='linux', hostname='localhost')

    rc = sync_mod.sync(direction='pull', remote=remote, root=dst_root)
    assert rc == 0, 'sync() must exit 0'

    dst_run = dst_root / 'artifacts' / '202605180800_000002_pull'
    assert dst_run.is_dir(), 'run dir must reach local from remote over ssh'
    _assert_run_filtered(dst_run)
    _assert_artifacts_sentinels_filtered(dst_root / 'artifacts')
