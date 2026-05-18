"""Tests for tools.runs.helpers.allocate_nnn — R4 flock-based allocator (T-03).

Covers spec §Atomic allocator 行 260-277:
- single-thread: empty → 1; existing max → max+1; non-NNN dirs skipped;
  sequential allocate is monotonically increasing.
- concurrent: two threads parallel must produce two *different* NNNs
  (the central TDD case — proves mkdir-inside-lock invariant holds).
- timeout: held flock + retry budget exhaustion raises
  ``RuntimeError('unable to acquire run-id lock after 10 retries')``.
- Windows dispatch: imports succeed, dispatch path routes to
  ``msvcrt.locking`` (mocked, since CI runs on macOS).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from unittest import mock

import pytest

from tools.runs import helpers


# --- Test helpers -------------------------------------------------------------


def _mk_artifact_dir(repo: Path, ts: str, nnn: int, label: str) -> Path:
    """Create an artifacts subdir matching the canonical naming regex.

    ``ts`` must be a 12-digit timestamp (YYYYMMDDHHMM) and ``nnn`` is
    zero-padded to 6 digits per spec.
    """
    artifacts = repo / 'artifacts'
    artifacts.mkdir(exist_ok=True)
    d = artifacts / f'{ts}_{nnn:06d}_{label}'
    d.mkdir()
    return d


def _caller_mkdir(repo: Path, ts: str, nnn: int, label: str) -> Path:
    """Simulate the T-08 caller path: under the allocate_nnn yield,
    mkdir the new artifacts dir before exiting the ``with`` block.
    """
    return _mk_artifact_dir(repo, ts, nnn, label)


# --- Single-thread allocation -------------------------------------------------


def test_allocate_empty_artifacts_returns_one(tmp_path: Path) -> None:
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 1
        _caller_mkdir(tmp_path, '202605180000', nnn, 'lbl')


def test_allocate_artifacts_dir_autocreated(tmp_path: Path) -> None:
    # tmp_path has no `artifacts/` subdir yet — allocator must create it.
    assert not (tmp_path / 'artifacts').exists()
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 1
    assert (tmp_path / 'artifacts').is_dir()
    assert (tmp_path / 'artifacts' / '.run_id_lock').is_file()


def test_allocate_with_existing_max_returns_max_plus_one(tmp_path: Path) -> None:
    _mk_artifact_dir(tmp_path, '202605180000', 5, 'lbl')
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 6


def test_allocate_with_existing_max_picks_highest_not_count(tmp_path: Path) -> None:
    # Gaps in the sequence: 3, 7, 12 → next should be 13, not 4.
    _mk_artifact_dir(tmp_path, '202605180000', 3, 'a')
    _mk_artifact_dir(tmp_path, '202605180001', 7, 'b')
    _mk_artifact_dir(tmp_path, '202605180002', 12, 'c')
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 13


def test_allocate_skips_non_nnn_dirs(tmp_path: Path) -> None:
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    # Pre-redesign legacy / arbitrary names — must not affect max.
    (artifacts / 'pre_redesign').mkdir()
    (artifacts / 'r001_legacy').mkdir()
    (artifacts / 's068_smoke').mkdir()
    # And one canonical dir at NNN=4 — should be the floor.
    _mk_artifact_dir(tmp_path, '202605180000', 4, 'lbl')
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 5


def test_allocate_skips_lock_file_and_other_files(tmp_path: Path) -> None:
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    # A regular file with NNN-looking name should be ignored (we only
    # scan directories).
    (artifacts / '202605180000_000099_lbl').write_text('not a dir')
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 1


def test_allocate_skips_partial_match(tmp_path: Path) -> None:
    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    # Wrong timestamp width (11 digits not 12) → must not match regex.
    (artifacts / '20260518000_000099_lbl').mkdir()
    # Wrong NNN width (5 digits) → must not match.
    (artifacts / '202605180000_00099_lbl').mkdir()
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 1


def test_allocate_sequential_is_monotonic(tmp_path: Path) -> None:
    seen: list[int] = []
    for i in range(5):
        with helpers.allocate_nnn(tmp_path) as nnn:
            seen.append(nnn)
            _caller_mkdir(tmp_path, f'2026051800{i:02d}', nnn, 'lbl')
    assert seen == [1, 2, 3, 4, 5]


def test_allocate_yields_int_not_str(tmp_path: Path) -> None:
    with helpers.allocate_nnn(tmp_path) as nnn:
        assert isinstance(nnn, int)
        assert nnn >= 1


# --- Concurrent allocation (central TDD case) ---------------------------------


def test_allocate_two_threads_parallel_get_different_nnn(tmp_path: Path) -> None:
    """Two threads racing through allocate_nnn must observe distinct
    NNNs. The mkdir-inside-lock invariant ensures thread 2 sees
    thread 1's dir on its re-glob inside the critical section.
    """
    barrier = threading.Barrier(2)
    results: dict[str, int] = {}
    errors: dict[str, BaseException] = {}

    def worker(name: str) -> None:
        try:
            barrier.wait(timeout=5)
            with helpers.allocate_nnn(tmp_path) as nnn:
                # Sleep briefly while holding the lock so the second
                # thread is forced to contend (not just sequentially
                # slip in after the first has released).
                time.sleep(0.05)
                _caller_mkdir(tmp_path, f'2026051800{ord(name[0]) % 60:02d}', nnn, name)
                results[name] = nnn
        except BaseException as e:  # noqa: BLE001
            errors[name] = e

    t1 = threading.Thread(target=worker, args=('alpha',))
    t2 = threading.Thread(target=worker, args=('beta',))
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f'worker errors: {errors}'
    assert set(results.keys()) == {'alpha', 'beta'}
    assert results['alpha'] != results['beta']
    assert set(results.values()) == {1, 2}


def test_allocate_many_threads_all_distinct(tmp_path: Path) -> None:
    """Scale the parallel case to N=8 threads; every NNN unique."""
    n_threads = 8
    barrier = threading.Barrier(n_threads)
    results: list[int] = []
    results_lock = threading.Lock()
    errors: list[BaseException] = []

    def worker(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
            with helpers.allocate_nnn(tmp_path) as nnn:
                _caller_mkdir(tmp_path, f'2026051800{idx:02d}', nnn, f'w{idx}')
                with results_lock:
                    results.append(nnn)
        except BaseException as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f'worker errors: {errors}'
    assert len(results) == n_threads
    assert len(set(results)) == n_threads, f'NNN collisions: {sorted(results)}'
    assert set(results) == set(range(1, n_threads + 1))


# --- Timeout / retry budget ---------------------------------------------------


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX flock path; Windows uses msvcrt')
def test_allocate_blocked_by_held_lock_raises_after_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A second allocator while the first holds the lock must exhaust
    its 10-retry budget and raise the canonical RuntimeError.

    Monkeypatch sleep so the test doesn't take 500ms+ of real wall.
    """
    import fcntl

    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    lock_path = artifacts / '.run_id_lock'

    monkeypatch.setattr(helpers.time, 'sleep', lambda _s: None)
    monkeypatch.setattr(helpers.random, 'uniform', lambda _a, _b: 0.0)

    # Hold the lock from this thread; allocator runs from another
    # thread to avoid recursive flock on the same fd (which would
    # silently succeed on some platforms).
    holder_fd = open(lock_path, 'a+')
    try:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        err_box: dict[str, BaseException] = {}

        def attempt() -> None:
            try:
                with helpers.allocate_nnn(tmp_path):
                    pass
            except BaseException as e:  # noqa: BLE001
                err_box['e'] = e

        t = threading.Thread(target=attempt)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), 'allocator thread did not return'

        assert 'e' in err_box, 'expected RuntimeError, allocator returned cleanly'
        err = err_box['e']
        assert isinstance(err, RuntimeError)
        # Full match (not substring) — pin spec 行 306 prescribed wording
        # exactly, so any drift (missing hint suffix, rewording) fails the
        # test loudly.
        assert str(err) == 'unable to acquire run-id lock after 10 retries; check artifacts/.run_id_lock'
        # Cause chain: BlockingIOError from the last failed attempt.
        assert err.__cause__ is not None
    finally:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_UN)
        holder_fd.close()


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX flock path; Windows uses msvcrt')
def test_allocate_retry_budget_is_exactly_ten(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Verify spec 行 276 ("retry up to 10 次") via call count on sleep.

    Sleep fires between attempts (not after the final one), so on a
    10-attempt budget that always fails we expect 9 sleeps.
    """
    import fcntl

    artifacts = tmp_path / 'artifacts'
    artifacts.mkdir()
    lock_path = artifacts / '.run_id_lock'

    sleep_calls: list[float] = []
    monkeypatch.setattr(helpers.time, 'sleep', lambda s: sleep_calls.append(s))
    monkeypatch.setattr(helpers.random, 'uniform', lambda _a, _b: 0.01)

    holder_fd = open(lock_path, 'a+')
    try:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        err_box: dict[str, BaseException] = {}

        def attempt() -> None:
            try:
                with helpers.allocate_nnn(tmp_path):
                    pass
            except BaseException as e:  # noqa: BLE001
                err_box['e'] = e

        t = threading.Thread(target=attempt)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()
        assert isinstance(err_box.get('e'), RuntimeError)
        # 10 attempts, 9 sleeps in between (no sleep after last
        # attempt — see allocator implementation).
        assert len(sleep_calls) == 9, f'expected 9 sleep calls, got {len(sleep_calls)}'
    finally:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_UN)
        holder_fd.close()


# --- Cross-platform dispatch --------------------------------------------------


def test_module_imports_on_current_platform() -> None:
    """Sanity: the module loaded; allocate_nnn callable; whichever
    platform branch is active, it exposed the right primitive."""
    assert callable(helpers.allocate_nnn)
    if sys.platform == 'win32':
        import msvcrt  # noqa: F401 — implicit assertion via import
    else:
        import fcntl  # noqa: F401


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX flock path; Windows test in own module')
def test_posix_dispatch_uses_fcntl_flock(tmp_path: Path) -> None:
    """On POSIX, the lock acquire path must call fcntl.flock with
    LOCK_EX | LOCK_NB — proves we didn't accidentally fall into a
    blocking variant.
    """
    with mock.patch.object(helpers.fcntl, 'flock', wraps=helpers.fcntl.flock) as spy:
        with helpers.allocate_nnn(tmp_path) as nnn:
            assert nnn == 1
        spy.assert_called()
        _fd, flags = spy.call_args.args
        assert flags == helpers.fcntl.LOCK_EX | helpers.fcntl.LOCK_NB


def test_windows_dispatch_routes_to_msvcrt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Simulate the Windows branch: monkey ``sys.platform`` + inject a
    fake ``msvcrt`` module into ``helpers``, then drive a single
    allocation. The fake's ``locking`` must be called with
    ``LK_NBLCK, 1`` per spec line 263. We don't actually run on
    Windows in CI, so this is a dispatch-routing assertion only.
    """
    fake_msvcrt = mock.MagicMock()
    fake_msvcrt.LK_NBLCK = 1
    fake_msvcrt.locking = mock.MagicMock(return_value=None)

    monkeypatch.setattr(helpers.sys, 'platform', 'win32')
    monkeypatch.setattr(helpers, 'msvcrt', fake_msvcrt, raising=False)

    with helpers.allocate_nnn(tmp_path) as nnn:
        assert nnn == 1

    fake_msvcrt.locking.assert_called()
    _fileno, mode, nbytes = fake_msvcrt.locking.call_args.args
    assert mode == fake_msvcrt.LK_NBLCK
    assert nbytes == 1
