"""``tools.runs.mark`` — flip a run's status to a terminal state.

Clean-slate redesign per
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§CLI mark 细则 HIGH-1-D 行 127-135 + HIGH-6-A 行 129-131 +
§Status 状态机 strict transitions 行 207-234.

Use case: when a ``running`` run dies externally (SIGKILL / power loss)
or a ``recover``-rebuilt ``unknown`` run needs final disposition, the
user runs ``mark <NNN> --status {done|failed|killed} [--notes ...]`` to
collapse the lifecycle to a terminal state.

Constraints (spec strict):

- ``{running, unknown} → {done, failed, killed}`` are the only mark
  transitions. ``{done, failed, killed} → anything`` raises
  :class:`schema.InvalidTransition` — terminal states are frozen, the
  only escape is ``resume`` (which is a train code-path, not a mark
  operation).
- ``--notes`` body goes through :func:`schema.dumps` (R1 emitter), which
  escapes raw newlines / control chars (``\\n`` → ``\\\\n`` etc) so a
  malicious-looking ``]\\n[other_section]`` cannot corrupt the TOML
  structure.
- The read → validate_transition → write sequence happens **inside a
  single per-run** ``acquire_metadata_lock``, so a concurrent train
  Phase C close cannot slip between our read and write (mirroring
  ``_train/run.py:_close_metadata_atomic`` pattern; spec 行 282).

Why the lock + inline write (not :func:`write_metadata_atomic`):
``write_metadata_atomic`` re-acquires the per-run flock internally, so
calling it from within our outer ``acquire_metadata_lock`` would
deadlock on Linux (cross-fd same-process flock blocks; retry budget
exhausts → ``RuntimeError``). We need the outer lock to make the
read-and-compare-and-write atomic, so we write inline (validate → temp
file → ``os.replace``) — exactly the pattern T-10
:func:`_close_metadata_atomic` uses for the same reason.

CLI::

    .venv/bin/python -m tools.runs.mark <NNN> --status done|failed|killed [--notes <text>]

Exit codes:

- 0 — mark succeeded
- 2 — lookup failure / invalid transition / IO error
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from tools.runs import schema
from tools.runs._helpers.locks import acquire_metadata_lock
from tools.runs._helpers.resolver import resolve_nnn_to_dir

# Mark-permitted target statuses (spec §Status 状态机 行 228-229).
# Excludes ``running`` (auto-only, by train Phase B init) and ``unknown``
# (recover-only — spec 行 220 "recover 命令入口").
_MARK_TARGETS: tuple[str, ...] = ('done', 'failed', 'killed')


def mark_run(repo_root: Path, nnn: str, new_status: str, notes: str | None) -> None:
    """Mark the run identified by ``nnn`` to ``new_status``.

    Atomic read-validate-write pattern:

    1. Resolve NNN shorthand → unique ``artifacts/`` dir via R7
       :func:`resolve_nnn_to_dir` (LookupError on 0 or ≥2 matches).
    2. Acquire per-run ``.metadata_lock`` (spec 行 282 + 135).
    3. Read current ``metadata.toml``.
    4. Validate ``current.status → new_status`` via
       :func:`schema.validate_transition` (``resume=False`` → strict;
       terminal states reject every target).
    5. Construct updated record. If ``notes is None``, preserve the
       existing ``notes``; else overwrite (TOML escape via
       :func:`schema.dumps` — raw ``\\n`` / control chars get
       backslash-escaped, no injection risk).
    6. Inline temp + ``os.replace`` write (sibling temp ensures
       single-mount atomic rename per HIGH-5-B).

    All other metadata fields (``wall_seconds`` / ``exit_code`` /
    ``timestamp`` / cfg / git / host / artifacts_dir) are carried over
    unchanged — mark only touches ``status`` and ``notes``. ``wall_seconds``
    for a dead ``running`` run will stay ``0.0`` (initial value from
    Phase B); user can override via ``--notes`` if they need to record
    "actually ran ~N hours before kill". Production decision: don't
    speculate wall time on dead runs.

    Args:
        repo_root: Repo root (production: ``Path.cwd()``).
        nnn: 1-6 digit NNN shorthand. Zero-padded to 6 digits internally.
        new_status: One of ``'done'``, ``'failed'``, ``'killed'``.
        notes: New free-form notes. ``None`` preserves existing notes.

    Raises:
        ValueError: ``nnn`` malformed (caller bug; from resolver) or
            ``new_status`` not in :data:`_MARK_TARGETS` (caller bug; CLI
            argparse should reject earlier).
        LookupError: 0 or ≥2 ``artifacts/`` dirs match the NNN.
        schema.InvalidTransition: ``current.status → new_status`` not
            allowed (e.g. ``done → done``: terminal states are frozen).
        OSError: filesystem IO failure (rare; surfaces as exit 2).
    """
    if new_status not in _MARK_TARGETS:
        # Defense in depth — argparse choices=... should catch this first.
        raise ValueError(f'mark target {new_status!r} must be one of {list(_MARK_TARGETS)}')

    artifacts_dir = resolve_nnn_to_dir(repo_root, nnn)
    target_path = artifacts_dir / 'metadata.toml'
    temp_path = artifacts_dir / 'metadata.toml.tmp'

    with acquire_metadata_lock(artifacts_dir):
        current = schema.load_file(target_path)

        # Strict transition check (resume=False) — terminal states reject
        # every mark target; raise InvalidTransition before any IO.
        schema.validate_transition(current.status, new_status, resume=False)

        updated = replace(
            current,
            status=new_status,
            notes=notes if notes is not None else current.notes,
        )

        # Inline temp + rename — schema.dumps validates + TOML-escapes
        # the new notes (spec 行 132-134); failures leave the original
        # metadata.toml untouched and the partial temp is best-effort
        # cleaned up.
        payload = schema.dumps(updated)
        try:
            temp_path.write_text(payload, encoding='utf-8')
            os.replace(temp_path, target_path)
        except BaseException:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass
            raise


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        'nnn',
        help='NNN shorthand: 1-6 digit run id (e.g. 69, 069, 000069). Internal zero-pad to 6 digits.',
    )
    ap.add_argument(
        '--status',
        choices=list(_MARK_TARGETS),
        required=True,
        help='Terminal status to flip to. Source status must be running or unknown (terminal states frozen).',
    )
    ap.add_argument(
        '--notes',
        default=None,
        help='Optional free-form notes (replaces existing). Raw newlines / control chars auto-escaped via TOML emitter.',
    )
    # --root undocumented but supported for tests; production runs cwd.
    ap.add_argument('--root', default=None, help=argparse.SUPPRESS)
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    repo_root = Path(args.root) if args.root else Path.cwd()
    try:
        mark_run(repo_root, args.nnn, args.status, args.notes)
    except (LookupError, schema.InvalidTransition, ValueError, OSError) as e:
        print(f'tools.runs.mark: {e}', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
