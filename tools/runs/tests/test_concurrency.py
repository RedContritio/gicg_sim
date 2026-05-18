"""T-26 — Concurrency test for ``tools.runs.train`` (subprocess level).

Spec ref: ``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``:

- 行 260-277 §Atomic allocator — flock + 10-retry budget + canonical
  ``'unable to acquire run-id lock after 10 retries; check
  artifacts/.run_id_lock'`` raise wording.
- 行 402-405 §测试矩阵 §Concurrency tests — 2 parallel ``train`` →
  assert 2 不同 NNN 分配 + 2 个 artifacts dir;run-id lock 模拟竞争 →
  assert retry + 最终成功 (here: retry then exhaustion raise — the
  "成功" branch is already covered in
  ``test_helpers_allocator.test_allocate_many_threads_all_distinct``
  in-process; subprocess-level we exercise the failure boundary instead
  because there is no clean way for a fixture process to release a
  flock with deterministic timing between subprocess attempts).

Companion to ``test_helpers_allocator.py`` (in-process threads) and
``test_train_dispatch_smoke.py`` (single-paradigm subprocess). This
file covers the **subprocess + parallel** quadrant that neither of
those reaches: two real OS processes contending on the kernel flock.

Wall budget: each DMC subprocess ~60-90s with default smoke cfg; we
override ``paradigm.dmc.total_frames=10`` to short-circuit Phase C
training to ≤ ~15s per process. Two parallel subprocesses share CPU
so wall ≤ ~30s typically. Marker: ``smoke`` (matches 60s/paradigm
tier budget per ``pyproject.toml`` markers section).

Run with ``-n 1`` (xdist) — the test itself spawns 2 concurrent
subprocesses; outer ``-n > 1`` would multiply the load.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from training.tests.smoke_full_template import REPO_ROOT, make_workspace

# Per-subprocess subprocess.run / Popen.wait timeout. Each DMC subprocess
# with total_frames=10 should finish ≤ ~15s on Mac CPU; 120s = 8× safety
# margin for parallel CPU contention + slower CI hosts.
_SUBPROCESS_TIMEOUT_S = 120

# Phase A allocator → mkdir → returns a per-run dir name matching
# ``^\d{12}_\d{6}_<label>`` (spec dir convention). Used to filter
# allocator state files (``.run_id_lock`` etc) out of artifacts/ scans.
_RUN_DIR_RE = re.compile(r'^(\d{12})_(\d{6})_')


def _dmc_train_cmd(cfg_path: Path) -> list[str]:
    """Build the ``python -m tools.runs.train`` argv with smoke-fast overrides.

    ``paradigm.dmc.total_frames=10`` caps Phase C to a handful of env
    steps so the subprocess finishes in seconds — the concurrency
    invariant is at Phase A (NNN allocation), not Phase C duration.
    """
    return [
        sys.executable,
        '-m',
        'tools.runs.train',
        str(cfg_path),
        '--override',
        'paradigm.dmc.total_frames=10',
    ]


def _list_run_dirs(artifacts_root: Path) -> list[Path]:
    """Return per-run dirs under ``artifacts_root`` (filters allocator state files)."""
    if not artifacts_root.is_dir():
        return []
    return sorted(d for d in artifacts_root.iterdir() if d.is_dir() and _RUN_DIR_RE.match(d.name) is not None)


@pytest.mark.smoke
def test_parallel_subprocesses_get_distinct_nnns(tmp_path: Path) -> None:
    """Two ``tools.runs.train`` subprocesses launched in parallel must
    each receive a distinct NNN and produce a separate per-run dir.

    The mkdir-inside-allocator-lock invariant (spec 行 269-275 +
    ``_helpers/allocator.py`` 行 75-80) guarantees the second process'
    re-glob inside its critical section observes process 1's freshly
    mkdir'd dir, so the second NNN strictly = first NNN + 1.

    Pre-condition: fresh ``workspace/artifacts/`` (no pre-existing run
    dirs), so allocator starts from 0. Post-condition: exactly 2 run
    dirs with NNNs (1, 2) — not (1, 1) (collision) or (1, 3) (skipped).
    """
    workspace = make_workspace(tmp_path)
    # Use the workspace's copied configs/ so Phase B normalize_repo_relative
    # accepts the cfg path (resolves under workspace, not the real repo).
    cfg_path = workspace / 'configs' / 'dmc' / 'smoke.toml'
    assert cfg_path.exists(), f'DMC smoke cfg missing under workspace: {cfg_path}'

    env = os.environ.copy()

    procs: list[subprocess.Popen[str]] = []
    try:
        for _ in range(2):
            p = subprocess.Popen(
                _dmc_train_cmd(cfg_path),
                cwd=str(workspace),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            procs.append(p)

        # Collect output with bounded wait so a hung subprocess doesn't
        # stall the test forever; communicate() honors the timeout
        # signal-safely (kill on timeout via the finally block).
        results: list[tuple[int, str, str]] = []
        for p in procs:
            out, err = p.communicate(timeout=_SUBPROCESS_TIMEOUT_S)
            results.append((p.returncode, out, err))
    finally:
        for p in procs:
            if p.poll() is None:
                p.kill()
                try:
                    p.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    pass

    # Both must exit 0 — Phase A's mkdir-inside-lock invariant means
    # contention cannot manifest as failure on either side (allocator
    # internally retries up to 10× on flock contention with ≤ 50ms
    # backoff; 2-process contention always wins inside the budget).
    for i, (rc, out, err) in enumerate(results):
        assert rc == 0, f'subprocess {i} exit={rc} (expected 0)\nSTDOUT:\n{out}\n\nSTDERR:\n{err}'

    # Exactly 2 per-run dirs created under workspace/artifacts/.
    artifacts_root = workspace / 'artifacts'
    run_dirs = _list_run_dirs(artifacts_root)
    assert len(run_dirs) == 2, (
        f'expected 2 per-run dirs, got {len(run_dirs)}: {[d.name for d in run_dirs]}\n'
        f'subprocess 0 stderr:\n{results[0][2]}\n\nsubprocess 1 stderr:\n{results[1][2]}'
    )

    # Distinct NNNs, consecutive starting from 1 (fresh artifacts root).
    nnns = sorted(int(_RUN_DIR_RE.match(d.name).group(2)) for d in run_dirs)
    assert nnns == [1, 2], f'expected NNNs [1, 2], got {nnns} (dirs: {[d.name for d in run_dirs]})'

    # Both metadata files closed cleanly (status='done', exit_code=0) —
    # asserts Phase C ran end-to-end despite Phase A contention.
    for d in run_dirs:
        metadata = tomllib.loads((d / 'metadata.toml').read_text(encoding='utf-8'))
        assert metadata['status'] == 'done', f'{d.name}: status={metadata["status"]!r}'
        assert metadata['exit_code'] == 0, f'{d.name}: exit_code={metadata["exit_code"]}'


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX fcntl.flock path; Windows uses msvcrt')
def test_allocator_retry_exhaustion_when_lock_held(tmp_path: Path) -> None:
    """Externally held ``.run_id_lock`` → subprocess exhausts 10-retry
    budget → SystemExit(2) with the spec 行 306 canonical wording.

    The fixture process pre-acquires the kernel-tracked flock on
    ``artifacts/.run_id_lock`` and holds it for the entire subprocess
    lifetime. The subprocess' allocator hits ``BlockingIOError`` on
    every attempt → retries 10× (each with ≤ 50ms backoff = ≤ 500ms
    total) → raises ``RuntimeError(<spec wording>)`` → top-level
    ``main`` catches as generic ``Exception`` → exits 2 with stderr
    ``'tools.runs.train: setup failed: <RuntimeError msg>'``.

    Spec-pinned: the RuntimeError text must match 行 306 wording
    verbatim (``'unable to acquire run-id lock after 10 retries; check
    artifacts/.run_id_lock'``). Any drift in the canonical wording
    breaks this test loudly — same pin as
    ``test_helpers_allocator.test_allocate_blocked_by_held_lock_raises_after_retries``
    just at the subprocess + CLI exit-code boundary.
    """
    import fcntl

    workspace = make_workspace(tmp_path)
    cfg_path = workspace / 'configs' / 'dmc' / 'smoke.toml'
    assert cfg_path.exists()

    # Pre-create artifacts/ + .run_id_lock so we can hold the flock from
    # the fixture process. Allocator's ``open('a+')`` will see the
    # existing file and immediately ``flock(LOCK_EX | LOCK_NB)`` →
    # ``BlockingIOError`` since we hold the kernel lock.
    artifacts_root = workspace / 'artifacts'
    artifacts_root.mkdir(parents=True, exist_ok=True)
    lock_path = artifacts_root / '.run_id_lock'
    lock_path.touch()

    holder_fd = open(lock_path, 'a+')
    try:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        completed = subprocess.run(
            _dmc_train_cmd(cfg_path),
            cwd=str(workspace),
            env=os.environ.copy(),
            timeout=_SUBPROCESS_TIMEOUT_S,
            capture_output=True,
            text=True,
        )
    finally:
        # Release + close regardless of subprocess outcome so a leaked
        # lock does not poison subsequent tests using the same tmp_path
        # tree (pytest's tmp_path is per-test, but defensive cleanup is
        # cheap and matches the equivalent in-process test pattern).
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_UN)
        holder_fd.close()

    # Exit code 2 — setup error per spec §Exit codes 行 253.
    assert completed.returncode == 2, (
        f'expected exit 2 (setup failure), got {completed.returncode}\n'
        f'STDOUT:\n{completed.stdout}\n\nSTDERR:\n{completed.stderr}'
    )

    # Stderr contains both the top-level ``setup failed: `` prefix from
    # ``train.main``'s ``except Exception`` handler AND the spec 行 306
    # canonical RuntimeError wording from the allocator.
    expected_msg = 'unable to acquire run-id lock after 10 retries; check artifacts/.run_id_lock'
    assert expected_msg in completed.stderr, f'expected stderr to contain {expected_msg!r}\nSTDERR:\n{completed.stderr}'
    assert 'setup failed' in completed.stderr, (
        f'expected stderr to contain "setup failed" prefix from main()\nSTDERR:\n{completed.stderr}'
    )

    # Phase A failed before mkdir → no per-run dirs created.
    run_dirs = _list_run_dirs(artifacts_root)
    assert run_dirs == [], f'expected no per-run dirs (Phase A failed pre-mkdir), got {[d.name for d in run_dirs]}'


def test_workspace_path_resolves_under_tmp(tmp_path: Path) -> None:
    """Sanity / regression: ``make_workspace`` returns a path under
    ``tmp_path`` (not the real repo) so the concurrency tests above
    never pollute production ``artifacts/``.

    Cheap guard against future refactors that might accidentally
    redirect ``make_workspace`` to ``REPO_ROOT`` (the BC fixture-import
    drift mode — symlinks back to repo would silently mkdir per-run
    dirs in the real tree).
    """
    workspace = make_workspace(tmp_path)
    assert workspace.is_relative_to(tmp_path), f'workspace {workspace} escaped tmp_path {tmp_path}'
    assert not workspace.is_relative_to(REPO_ROOT), f'workspace {workspace} aliases REPO_ROOT'
