"""tools.runs._train.run — Phase C lifecycle (steps 6-7).

Internal module — callers must use :mod:`tools.runs.train` (the public
entry shell). Implements lifecycle steps 6 and 7:

- step 6  run train via :func:`_run_train_placeholder` (T-11 — real
          paradigm dispatch: ``load_cfg`` from cfg_resolved.toml →
          paradigm registry → ``run_pipeline``; symbol name retained
          from T-10 stub so test monkeypatches on the call site keep
          working without renames)
- step 7  acquire per-run metadata_lock, **read metadata.status before
          overwrite**, update status to ``done``/``failed`` (or leave
          alone if externally marked), write ``wall_seconds`` +
          ``exit_code``

Exit-code contract (spec §Exit codes):

- 0  train done + metadata closed cleanly
- 1  train ran but failed mid-way (metadata=failed)
- 3  train done but final metadata write failed (metadata stays
     ``running``; user must run ``tools.runs.mark`` to close)

Note: spec §Exit codes also defines 2 (cfg / setup error) but Phase C
is reached only after Phase A + B succeed, so 2 cannot originate here.

External-mark handling (spec §单命令 atomic lifecycle): if a concurrent ``tools.runs.
mark`` flipped status away from ``running`` while train was executing,
Phase C **does not** overwrite — it preserves the mark and exits 0 with
a stderr warning. Treating an external mark as Phase C failure would
mean user-issued kill / done flags get clobbered the moment train
returns.

Lock interaction caveat (mirrors metadata_io.py warning):
:func:`write_metadata_atomic` re-acquires the per-run flock internally,
so wrapping it in our outer :func:`acquire_metadata_lock` would
deadlock on Linux (cross-fd same-process flock blocks; the retry
budget would then exhaust → ``RuntimeError``). Phase C performs the
final write inline (validate → temp file → ``os.replace``) within its
own outer lock to keep the read-and-compare-and-write fully atomic
per spec §metadata 写 without re-entering the helper.

Spec cross-refs (``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``):

- §Architecture step 6-7 (run + close)
- §单命令 atomic lifecycle step 7 read-and-compare-before-write
- §Exit codes table
- §metadata 写 metadata_lock read-and-compare-and-write atomicity
- §错误处理 train 失败时 (exception → failed, finally
             discipline never masks root cause)
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.locks import acquire_metadata_lock
from tools.runs._train import dispatch
from tools.runs._train.setup import SetupState


def _run_train_placeholder(state: SetupState) -> None:
    """Step 6 — paradigm dispatch + run_pipeline (T-11).

    Delegates to :func:`tools.runs._train.dispatch.run_paradigm_train`
    which owns the cfg → paradigm → ``run_pipeline`` wiring. Symbol
    name retained from the T-10 stub on purpose: Phase C tests in
    ``test_train_close.py`` monkeypatch this exact name to inject
    failures / external-mark simulations; renaming would silently
    invalidate those tests.

    The actual dispatch lives in :mod:`tools.runs._train.dispatch`
    (split per CLAUDE.md 300-line pre-commit budget — Phase C close
    logic + paradigm dispatch don't fit in one file). The wrapper here
    is intentionally one line so a future maintainer cannot accidentally
    add behaviour that test monkeypatches would silently bypass.
    """
    dispatch.run_paradigm_train(state)


def phase_c_run_train_and_close(state: SetupState) -> int:
    """Steps 6-7: run train + close metadata. Return process exit code.

    Lifecycle (spec §单命令 atomic lifecycle):

    1. ``time.monotonic()`` start (wall_seconds measurement)
    2. call :func:`_run_train_placeholder` (T-11: real paradigm dispatch)
    3. catch any :class:`BaseException` raised by train — save the
       exception, fall through to close logic (do NOT re-raise here;
       the close step needs to record ``status='failed'`` regardless
       of how train died)
    4. compute ``wall_seconds`` (monotonic delta)
    5. acquire per-run metadata_lock + read current metadata
    6. if ``current.status != 'running'``: someone else (``mark`` /
       ``recover``) already wrote a terminal state — log warn, return 0,
       do NOT overwrite (spec §单命令 atomic lifecycle)
    7. else: update ``status`` / ``wall_seconds`` / ``exit_code``, write
       inline (within the outer lock) via temp + ``os.replace``

    Return value:

    - 0 if train succeeded + metadata closed cleanly
    - 0 if metadata externally marked (spec §单命令 atomic lifecycle explicit "exit 0")
    - 1 if train failed and metadata closed as ``failed``
    - non-zero ``SystemExit.code`` if train raised :class:`SystemExit`
      with a non-None code (preserved as both exit_code field and
      process exit code; ``failed`` status)
    - 3 if step-7 close failed (metadata stays ``running``; user must
      run ``tools.runs.mark`` to close — spec §Exit codes)
    """
    start_monotonic = time.monotonic()
    train_exception: BaseException | None = None

    try:
        _run_train_placeholder(state)
    except BaseException as exc:  # noqa: BLE001 — step 6 must catch all per spec §单命令 atomic lifecycle
        train_exception = exc
        # Print the traceback BEFORE classify/close so operators see what
        # actually went wrong. Without this, the silent fall-through to
        # status='failed' + exit_code=1 leaves zero diagnostic trail
        # (training crashes look like "1.1s wall, exit 1, no stderr").
        # SystemExit(0) is the "clean exit" sentinel — don't noise the
        # log for it.
        import traceback

        if not (isinstance(exc, SystemExit) and (exc.code is None or exc.code == 0)):
            print(
                f'tools.runs.train: train raised {type(exc).__name__}; closing metadata as failed.',
                file=sys.stderr,
            )
            traceback.print_exception(type(exc), exc, exc.__traceback__, file=sys.stderr)

    wall_seconds = time.monotonic() - start_monotonic

    # Map train outcome → (status, exit_code) BEFORE acquiring the lock
    # so a malformed SystemExit.code (e.g. non-int) surfaces as the
    # primary error rather than being masked by a downstream IO bug.
    new_status, exit_code = _classify_train_outcome(train_exception)

    try:
        return _close_metadata_atomic(state.artifacts_dir, new_status, wall_seconds, exit_code)
    except BaseException as close_exc:  # noqa: BLE001 — final-write boundary, spec §Exit codes
        # Spec §Exit codes: final metadata write failed → exit 3; metadata
        # stays 'running' so operator can decide via tools.runs.mark.
        # Print path-bearing hint per spec §用户友好 error message.
        print(f'tools.runs.train: final metadata write failed: {close_exc}', file=sys.stderr)
        print(
            f"tools.runs.train: metadata at {state.artifacts_dir}/metadata.toml stays 'running'; "
            f"run 'tools.runs.mark <NNN> --status done/failed/killed' to close",
            file=sys.stderr,
        )
        return 3


def _classify_train_outcome(train_exception: BaseException | None) -> tuple[str, int]:
    """Map step-6 outcome to (new_status, exit_code) for the close write.

    - ``None`` (train returned normally) → ``('done', 0)``
    - :class:`SystemExit` with ``code=0`` or ``code=None`` → ``('done', 0)``;
      Python convention treats both as successful exit (``sys.exit()`` no-arg
      ↔ ``sys.exit(0)``). T-11 paradigm dispatch may explicitly
      ``sys.exit(0)`` on success and we should honor that as success rather
      than create an internally-inconsistent ``status='failed' + exit_code=0``
      record.
    - :class:`SystemExit` with non-zero int ``.code`` → ``('failed', code)``;
      preserves the train-chosen semantic exit code (e.g. paradigm could
      ``sys.exit(7)`` for a domain-specific failure mode).
    - :class:`SystemExit` with non-int ``.code`` (e.g. ``'string'``) →
      ``('failed', 1)``; the field type is ``int`` per schema so we cannot
      preserve a string code, fall back to catch-all 1.
    - Any other :class:`BaseException` → ``('failed', 1)``.

    Returning a tuple (rather than mutating state inline) keeps the
    classification logic unit-testable and separates "what did train do?"
    from "how do we persist that?".
    """
    if train_exception is None:
        return ('done', 0)
    if isinstance(train_exception, SystemExit):
        raw_code = train_exception.code
        if raw_code is None:
            return ('done', 0)
        if isinstance(raw_code, int) and not isinstance(raw_code, bool):
            if raw_code == 0:
                return ('done', 0)
            return ('failed', raw_code)
        # Non-int (string, etc.) — record failure with catch-all 1.
        return ('failed', 1)
    return ('failed', 1)


def _close_metadata_atomic(artifacts_dir: Path, new_status: str, wall_seconds: float, exit_code: int) -> int:
    """Lock + read + compare + write the final metadata. Return process exit code.

    All four steps (read, compare, write, rename) happen within a single
    :func:`acquire_metadata_lock` so a concurrent ``mark`` cannot slip
    between our read and write (spec §metadata 写). Inline write (validate →
    temp file → ``os.replace``) mirrors :func:`write_metadata_atomic`
    semantics minus the inner lock acquisition, sidestepping the
    re-entrant deadlock documented in metadata_io.py.

    Returns the desired process exit code:

    - ``0`` if externally marked (no overwrite) — spec §单命令 atomic lifecycle
    - mapped ``exit_code`` arg if we performed the close — spec §Exit codes

    Raises whatever underlying IO / validation error breaks the write;
    the caller maps that to exit 3 (spec §Exit codes).
    """
    target = artifacts_dir / 'metadata.toml'
    temp = artifacts_dir / 'metadata.toml.tmp'

    with acquire_metadata_lock(artifacts_dir):
        current = schema.load_file(target)
        if current.status != 'running':
            print(
                f'tools.runs.train: metadata externally marked as {current.status!r}, train output discarded',
                file=sys.stderr,
            )
            return 0

        # Validate the new transition (running → done/failed) before any
        # IO — an invalid transition (shouldn't happen given our
        # classifier, but defense-in-depth) raises InvalidTransition
        # before we touch the file.
        schema.validate_transition(current.status, new_status, resume=False)

        # Construct the updated record in place — all other fields
        # carry over unchanged (host/git_commit/cfg_file/etc are first-
        # train constants).
        updated = schema.RunMetadata(
            run_id=current.run_id,
            timestamp=current.timestamp,
            cfg_file=current.cfg_file,
            cfg_resolved_version=current.cfg_resolved_version,
            git_commit=current.git_commit,
            host=current.host,
            status=new_status,
            artifacts_dir=current.artifacts_dir,
            wall_seconds=float(wall_seconds),
            exit_code=int(exit_code),
            notes=current.notes,
        )

        payload = schema.dumps(updated)
        try:
            temp.write_text(payload, encoding='utf-8')
            os.replace(temp, target)
        except BaseException:
            # Best-effort temp cleanup; never mask the original.
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            raise

        return exit_code
