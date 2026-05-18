"""Tests for tools.runs.helpers.acquire_metadata_lock + write_metadata_atomic
— R5 + R6 (T-04).

Covers spec §metadata 写 行 279-286 + CRIT-2-B + CRIT-3-A + HIGH-5-B:
- per-run advisory flock: same artifacts_dir serializes, distinct
  artifacts_dirs do not contend.
- 10-retry budget + path-bearing timeout message.
- atomic rename via same-dir temp file (HIGH-5-B ban on
  ``tempfile.NamedTemporaryFile`` default args — grep-level guard).
- write interrupted mid-stream leaves target intact + cleans temp.
- two-thread parallel writes both succeed, final file is one whole
  payload (never mixed bytes).
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

import pytest

from tools.runs import helpers, schema
from tools.runs._helpers import locks as _locks
from tools.runs._helpers import metadata_io as _metadata_io


# --- Test helpers -------------------------------------------------------------


def _mk_meta(run_id: str = '000001', *, notes: str = '') -> schema.RunMetadata:
    """Return a minimal valid RunMetadata for write-path tests."""
    return schema.RunMetadata(
        run_id=run_id,
        timestamp='2026-05-18T00:00:00Z',
        cfg_file='configs/test.toml',
        cfg_resolved_version=1,
        git_commit='unknown',
        host='testhost',
        status='running',
        artifacts_dir=f'artifacts/202605180000_{run_id}_test',
        wall_seconds=0.0,
        exit_code=0,
        notes=notes,
    )


# --- acquire_metadata_lock: single-thread sanity ------------------------------


def test_metadata_lock_single_thread_acquire_release(tmp_path: Path) -> None:
    with helpers.acquire_metadata_lock(tmp_path):
        assert (tmp_path / '.metadata_lock').is_file()
    # Re-acquire after release works.
    with helpers.acquire_metadata_lock(tmp_path):
        pass


def test_metadata_lock_creates_artifacts_dir(tmp_path: Path) -> None:
    target = tmp_path / 'newrun'
    assert not target.exists()
    with helpers.acquire_metadata_lock(target):
        assert target.is_dir()
        assert (target / '.metadata_lock').is_file()


# --- acquire_metadata_lock: concurrency ---------------------------------------


def test_metadata_lock_same_dir_serializes(tmp_path: Path) -> None:
    """Two threads contending on the same artifacts_dir must serialize.

    We measure that the second thread cannot enter the critical
    section until the first releases — recorded by an event flag
    flipped under the lock.
    """
    barrier = threading.Barrier(2)
    inside = threading.Event()
    second_saw_first_inside = threading.Event()
    second_acquired = threading.Event()
    errors: dict[str, BaseException] = {}

    def first() -> None:
        try:
            barrier.wait(timeout=5)
            with helpers.acquire_metadata_lock(tmp_path):
                inside.set()
                # Hold long enough for second to attempt acquire.
                time.sleep(0.1)
        except BaseException as e:  # noqa: BLE001
            errors['first'] = e

    def second() -> None:
        try:
            barrier.wait(timeout=5)
            # Wait until first is inside, then attempt acquire.
            assert inside.wait(timeout=5)
            second_saw_first_inside.set()
            with helpers.acquire_metadata_lock(tmp_path):
                second_acquired.set()
        except BaseException as e:  # noqa: BLE001
            errors['second'] = e

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    t2.start()
    t1.join(timeout=10)
    t2.join(timeout=10)

    assert not errors, f'errors: {errors}'
    assert second_saw_first_inside.is_set()
    assert second_acquired.is_set()


def test_metadata_lock_distinct_dirs_do_not_contend(tmp_path: Path) -> None:
    """Per-run scope: locking dir-A must not block dir-B."""
    dir_a = tmp_path / 'a'
    dir_b = tmp_path / 'b'
    dir_a.mkdir()
    dir_b.mkdir()

    b_acquired = threading.Event()
    errors: dict[str, BaseException] = {}

    def second() -> None:
        try:
            with helpers.acquire_metadata_lock(dir_b):
                b_acquired.set()
        except BaseException as e:  # noqa: BLE001
            errors['b'] = e

    with helpers.acquire_metadata_lock(dir_a):
        # While A is held, B should acquire promptly.
        t = threading.Thread(target=second)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), 'B thread blocked on A — per-run scope violated'
        assert b_acquired.is_set()

    assert not errors, f'errors: {errors}'


# --- acquire_metadata_lock: timeout ------------------------------------------


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX flock path; Windows uses msvcrt')
def test_metadata_lock_blocked_raises_after_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Held lock + retry budget exhaustion → RuntimeError with
    artifacts_dir path in the message."""
    import fcntl

    tmp_path.mkdir(exist_ok=True)
    lock_path = tmp_path / '.metadata_lock'

    monkeypatch.setattr(_locks.time, 'sleep', lambda _s: None)
    monkeypatch.setattr(_locks.random, 'uniform', lambda _a, _b: 0.0)

    holder_fd = open(lock_path, 'a+')
    try:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        err_box: dict[str, BaseException] = {}

        def attempt() -> None:
            try:
                with helpers.acquire_metadata_lock(tmp_path):
                    pass
            except BaseException as e:  # noqa: BLE001
                err_box['e'] = e

        t = threading.Thread(target=attempt)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive()

        assert 'e' in err_box
        err = err_box['e']
        assert isinstance(err, RuntimeError)
        msg = str(err)
        assert 'metadata lock' in msg
        # Path-bearing hint for operator inspection.
        assert str(tmp_path) in msg
        assert '.metadata_lock' in msg
        # Cause chain: BlockingIOError from the last failed attempt.
        assert err.__cause__ is not None
    finally:
        fcntl.flock(holder_fd.fileno(), fcntl.LOCK_UN)
        holder_fd.close()


# --- write_metadata_atomic: happy path ----------------------------------------


def test_write_metadata_atomic_creates_target(tmp_path: Path) -> None:
    meta = _mk_meta(notes='hello')
    helpers.write_metadata_atomic(tmp_path, meta)

    target = tmp_path / 'metadata.toml'
    assert target.is_file()
    # Content equals canonical dumps (no extra bytes from temp suffix
    # leaking through).
    assert target.read_text(encoding='utf-8') == schema.dumps(meta)
    # Temp file cleaned up.
    assert not (tmp_path / 'metadata.toml.tmp').exists()


def test_write_metadata_atomic_roundtrip(tmp_path: Path) -> None:
    meta = _mk_meta(notes='roundtrip-ok')
    helpers.write_metadata_atomic(tmp_path, meta)
    loaded = schema.load_file(tmp_path / 'metadata.toml')
    assert loaded == meta


def test_write_metadata_atomic_overwrites_existing(tmp_path: Path) -> None:
    helpers.write_metadata_atomic(tmp_path, _mk_meta(notes='first'))
    helpers.write_metadata_atomic(tmp_path, _mk_meta(notes='second'))
    loaded = schema.load_file(tmp_path / 'metadata.toml')
    assert loaded.notes == 'second'


# --- write_metadata_atomic: same-dir temp invariant (HIGH-5-B) ---------------


def test_write_metadata_atomic_temp_file_same_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Temp file path must be a sibling of the target — cross-mount
    rename is non-atomic, so spec HIGH-5-B requires same-dir temp.
    """
    seen_temp_path: dict[str, Path] = {}
    real_write_text = Path.write_text

    def spy_write_text(self: Path, *args: object, **kwargs: object) -> int:
        if self.name == 'metadata.toml.tmp':
            seen_temp_path['p'] = self
        return real_write_text(self, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(Path, 'write_text', spy_write_text)

    meta = _mk_meta()
    helpers.write_metadata_atomic(tmp_path, meta)

    assert 'p' in seen_temp_path
    temp = seen_temp_path['p']
    assert temp.parent == tmp_path, f'temp must be sibling of target; got parent={temp.parent}'
    assert temp.name == 'metadata.toml.tmp'


def _helpers_source_files() -> list[Path]:
    """Return every .py source file backing tools.runs.helpers — the
    public shell plus every module in the ``_helpers/`` internal
    package. AST guards walk all of them so future regression cannot
    sneak ``tempfile`` in via a new helper file.
    """
    runs_dir = Path(__file__).resolve().parents[1]
    files = [runs_dir / 'helpers.py']
    files.extend(sorted((runs_dir / '_helpers').glob('*.py')))
    return files


def test_write_metadata_implementation_forbids_namedtemporaryfile() -> None:
    """Static AST guard: the implementation must not import or call
    ``tempfile.NamedTemporaryFile`` (spec HIGH-5-B explicit ban — default
    dir is /tmp which may be a different mount, breaking atomic rename).

    Walks the AST so docstring / comment mentions of the literal string
    (we explicitly document why it's banned) don't false-positive — we
    only flag actual import / attribute access / call sites. Scans the
    public ``helpers.py`` shell + every module in the ``_helpers/``
    internal package (R6 lives in ``_helpers/metadata_io.py``).
    """
    import ast

    offenders: list[str] = []
    for src in _helpers_source_files():
        tree = ast.parse(src.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            # `from tempfile import NamedTemporaryFile [as X]`
            if isinstance(node, ast.ImportFrom) and node.module == 'tempfile':
                for alias in node.names:
                    if alias.name == 'NamedTemporaryFile':
                        offenders.append(f'{src.name}:{node.lineno}: from tempfile import NamedTemporaryFile')
            # `import tempfile` is fine by itself, but `tempfile.NamedTemporaryFile(...)`
            # attribute access (or any reference) is flagged.
            if (
                isinstance(node, ast.Attribute)
                and node.attr == 'NamedTemporaryFile'
                and isinstance(node.value, ast.Name)
                and node.value.id == 'tempfile'
            ):
                offenders.append(f'{src.name}:{node.lineno}: tempfile.NamedTemporaryFile attribute access')
            # Bare `NamedTemporaryFile(...)` call — would only resolve if imported,
            # which the ImportFrom check above catches; included for completeness.
            if isinstance(node, ast.Name) and node.id == 'NamedTemporaryFile':
                offenders.append(f'{src.name}:{node.lineno}: bare NamedTemporaryFile name reference')

    assert not offenders, (
        f'helpers package must not use tempfile.NamedTemporaryFile (spec HIGH-5-B); offenders: {offenders}'
    )


def test_write_metadata_no_tempfile_import_at_all() -> None:
    """Belt-and-suspenders: ``tempfile`` module should not be imported
    anywhere in the helpers package. R6 uses an explicit sibling temp
    file path (``<artifacts_dir>/metadata.toml.tmp``) — there's no
    legitimate use for ``tempfile.*`` in this package. Guards future
    drift where someone might add e.g. ``tempfile.mkstemp(dir=artifacts_dir)``
    and accidentally drop the ``dir=`` arg.
    """
    import ast

    for src in _helpers_source_files():
        tree = ast.parse(src.read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != 'tempfile', (
                        f'{src.name}:{node.lineno}: tempfile import not allowed in helpers package'
                    )
            if isinstance(node, ast.ImportFrom):
                assert node.module != 'tempfile', (
                    f'{src.name}:{node.lineno}: from tempfile import ... not allowed in helpers package'
                )


# --- write_metadata_atomic: failure modes ------------------------------------


def test_write_metadata_atomic_replace_failure_preserves_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If os.replace raises mid-write, the existing target stays intact
    and the temp file is best-effort cleaned up."""
    # Pre-seed an existing valid metadata file.
    original = _mk_meta(notes='original')
    helpers.write_metadata_atomic(tmp_path, original)
    assert (tmp_path / 'metadata.toml').is_file()

    # Force os.replace to fail on the next write.
    def boom(_src: object, _dst: object) -> None:
        raise OSError('simulated rename failure')

    monkeypatch.setattr(_metadata_io.os, 'replace', boom)

    with pytest.raises(OSError, match='simulated rename failure'):
        helpers.write_metadata_atomic(tmp_path, _mk_meta(notes='clobbered'))

    # Target unchanged.
    loaded = schema.load_file(tmp_path / 'metadata.toml')
    assert loaded.notes == 'original'
    # Temp cleaned up.
    assert not (tmp_path / 'metadata.toml.tmp').exists()


def test_write_metadata_atomic_validate_failure_no_files(tmp_path: Path) -> None:
    """Invalid metadata must raise from schema.dumps before any file IO
    — no temp file, no target file."""
    # Build a metadata with invalid run_id (not 6-digit).
    bad = schema.RunMetadata(
        run_id='r001',  # legacy format — schema rejects
        timestamp='2026-05-18T00:00:00Z',
        cfg_file='configs/test.toml',
        cfg_resolved_version=1,
        git_commit='unknown',
        host='testhost',
        status='running',
        artifacts_dir='artifacts/x',
        wall_seconds=0.0,
        exit_code=0,
        notes='',
    )
    with pytest.raises(ValueError, match='run_id'):
        helpers.write_metadata_atomic(tmp_path, bad)

    assert not (tmp_path / 'metadata.toml').exists()
    assert not (tmp_path / 'metadata.toml.tmp').exists()


# --- write_metadata_atomic: parallel writers ----------------------------------


def test_write_metadata_atomic_parallel_writers_no_corruption(tmp_path: Path) -> None:
    """Two threads writing concurrently to the same artifacts_dir both
    succeed; the final file is one of the two payloads (whole — never
    a byte-level mix).
    """
    n_writers = 4
    barrier = threading.Barrier(n_writers)
    errors: list[BaseException] = []
    errors_lock = threading.Lock()

    def writer(idx: int) -> None:
        try:
            barrier.wait(timeout=5)
            meta = _mk_meta(notes=f'writer-{idx}')
            helpers.write_metadata_atomic(tmp_path, meta)
        except BaseException as e:  # noqa: BLE001
            with errors_lock:
                errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(n_writers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert not errors, f'parallel writer errors: {errors}'

    # Final file must parse cleanly and be one of the writers' payloads
    # (whole, not a partial / mixed write).
    loaded = schema.load_file(tmp_path / 'metadata.toml')
    assert loaded.notes.startswith('writer-')
    idx = int(loaded.notes.removeprefix('writer-'))
    assert 0 <= idx < n_writers
    # Temp file cleaned up.
    assert not (tmp_path / 'metadata.toml.tmp').exists()
