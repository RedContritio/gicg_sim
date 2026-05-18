"""tools.runs.train — single-command atomic lifecycle entry shell.

Sole entry point for training under the 2026-05-18 ``tools/runs/``
clean-slate redesign (spec
``docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md``
§Architecture 行 24-74).

Phase implementations live in :mod:`tools.runs._train` sub-package
(``_helpers/`` precedent from T-04). This shell is argparse + main
dispatch only — it re-exports :class:`SetupState` and selected
internals so existing tests / future Phase B/C helpers can import
either ``tools.runs.train`` (public surface) or
``tools.runs._train.<phase>`` (internal phase modules).

Lifecycle phases:

- Phase A (T-08): steps 0-3 — validate + capture + resolve + mkdir
- Phase B (T-09): steps 4-5 — write cfg_leaf.toml + cfg_resolved.toml + metadata.toml
- Phase C (T-10): steps 6-7 — run train + close metadata
- Phase D (T-11+): paradigm dispatch / resume / authoritative host

T-08 ``main()`` calls Phase A then prints a stub and exits 0. T-09
inserts the Phase B call between Phase A success and the stub.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Re-exports: keep public ``tools.runs.train.<symbol>`` surface stable
# for tests that import e.g. ``train_mod.SetupState`` /
# ``train_mod._phase_a_setup`` directly. The actual definitions live in
# :mod:`tools.runs._train.setup`; monkeypatching the UTC ts source or
# the SetupState ctor must target ``_train.setup`` (the call site),
# not this shell. Underscored re-exports are kept to preserve the
# public ``train_mod._<name>`` surface that tests use.
from tools.runs._train.setup import (  # noqa: F401
    SetupState,
    _extract_leaf_label,
    _RUN_LABEL_RE,
    _validate_run_label,
    _verify_repo_root,
    phase_a_setup as _phase_a_setup,
)
from tools.runs._train.snapshot import (  # noqa: F401
    phase_b_write_cfg_metadata as _phase_b_write_cfg_metadata,
)

__all__ = [
    'SetupState',
    'main',
]


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='tools.runs.train',
        description=(
            'Atomic train lifecycle (clean-slate redesign): allocate NNN, mkdir '
            'per-run dir, snapshot cfg, write metadata, run train, close metadata. '
            'T-08 ships steps 0-3 (setup + allocator); 4-7 land in T-09 / T-10.'
        ),
    )
    parser.add_argument('cfg', type=str, help='path to TOML cfg')
    parser.add_argument(
        '--override',
        action='append',
        default=[],
        metavar='KEY=VALUE',
        help='dotted-key override applied post-extends (repeatable)',
    )
    parser.add_argument(
        '--resume',
        type=str,
        default=None,
        help='ckpt path to resume from (parsed only; resume logic lands in T-12)',
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        state = _phase_a_setup(args)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary
        print(f'tools.runs.train: setup failed: {exc}', file=sys.stderr)
        return 2

    # Phase B: cfg_leaf.toml + cfg_resolved.toml + metadata.toml (status='running').
    # Failure path internally rmtree's the orphan dir + raises SystemExit(2)
    # — we let that propagate (the SystemExit handler in caller code, or
    # python interpreter top-level, prints the captured stderr). Other
    # unexpected exceptions are caught + mapped to exit 2 the same way as
    # Phase A above.
    try:
        _phase_b_write_cfg_metadata(state, Path(args.cfg))
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 — top-level CLI boundary
        print(f'tools.runs.train: cfg/metadata snapshot failed: {exc}', file=sys.stderr)
        return 2

    # Phase C placeholder — T-10 runs train + closes metadata. T-09 stops
    # here so Phase B can ship independently with full test coverage.
    print(f'[stub] Phase B complete: {state.artifacts_dir}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
