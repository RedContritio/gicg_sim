---
last_updated: 2026-09-17
status: LIVE
schema_version: 1
capability: tools-layout
---

# Tools layout and run lifecycle

This specification defines the current `tools/` organization and the single
training lifecycle introduced by the 2026-05-18 clean-slate redesign. The
pre-redesign `tools.run`, `tools.runs.register`, `tools.runs.complete`, and
`artifacts/runs/*.toml` interfaces are historical and must not be restored.

## Directory boundaries

1. General tools SHALL be grouped by function. Current groups include
   `_bench`, `_dev`, `_meta`, `bench`, `cards`, `ckpt`, `dataset`, `debug`,
   `dmc`, `eval`, `experiments`, `perf`, `probe`, `profile`, `replay`,
   `rule_validation`, and `runs`.
2. `tools/runs/` SHALL own the training lifecycle, run metadata, remote host
   wrappers, artifact transfer, status queries, and process control.
3. `tools/eval/` SHALL own reusable evaluation commands and the evaluation
   service. `tools/dataset/` SHALL own dataset generation and inspection.
4. `_meta/` SHALL contain repository maintenance and migration helpers. A
   deprecated helper kept for historical callers SHALL identify its successor
   in its module documentation and SHALL NOT be presented as the normal path.
5. New ad hoc experiments SHALL live under `tools/experiments/<topic>/` or an
   existing functional group. They SHALL NOT create a second training entry.

## Single training entry

6. `python -m tools.runs.train <cfg.toml>` SHALL be the only general training
   entry. It SHALL resolve `meta.paradigm` through the paradigm registry.
7. The entry SHALL atomically allocate a six-digit run number, create the run
   directory, capture leaf and resolved configuration, write initial metadata,
   run the selected paradigm, and close metadata.
8. `--override KEY=VALUE` SHALL apply after config inheritance. `--resume
   <ckpt>` SHALL reuse the original run number and append versioned
   `cfg_leaf_v<N>.toml` and `cfg_resolved_v<N>.toml` snapshots.
9. A fresh run directory SHALL match
   `artifacts/<YYYYMMDDHHMM>_<NNNNNN>_<run_label>/`, where the timestamp is
   UTC and the number is zero-padded to six digits.
10. Each run directory SHALL be self-contained:

    ```text
    metadata.toml
    cfg_leaf.toml
    cfg_resolved.toml
    ckpts/
    metrics.jsonl
    tb/                  # optional
    ```

11. `metadata.toml` SHALL use the 11-field schema implemented in
    `tools/runs/schema.py`: `run_id`, `timestamp`, `cfg_file`,
    `cfg_resolved_version`, `git_commit`, `host`, `status`, `artifacts_dir`,
    `wall_seconds`, `exit_code`, and `notes`.
12. Status SHALL be one of `running`, `done`, `failed`, `killed`, or `unknown`.
    Normal close changes `running` to a terminal status. `recover` alone creates
    `unknown`; `mark` changes `running` or `unknown` to a terminal status;
    resume may change any status back to `running`.

## Run commands

13. The supported local lifecycle commands are:

    ```bash
    .venv/bin/python -m tools.runs.train <cfg>
    .venv/bin/python -m tools.runs.train <cfg> --resume <ckpt>
    .venv/bin/python -m tools.runs.list [--status <status>] [--paradigm <name>]
    .venv/bin/python -m tools.runs.show <NNN>
    .venv/bin/python -m tools.runs.mark <NNN> --status done|failed|killed
    .venv/bin/python -m tools.runs.recover <artifacts-dir>
    ```

14. `list` SHALL scan direct children of `artifacts/` for `metadata.toml`,
    derive the paradigm and run label from the latest resolved config, sort by
    descending timestamp, and skip malformed records with a warning.
15. `show` and mutating commands SHALL resolve a 1-to-6-digit shorthand to one
    unique run directory and fail if no directory or multiple directories
    match.
16. Metadata writes SHALL use the per-run metadata lock and atomic replacement.
    Run-number and resume-version allocation SHALL use the allocator lock.

## Remote workflow

17. Remote execution SHALL be config-driven through `[meta].host = "remote"` and
    a `[remote].profile` name resolving to the git-ignored host registry, which
    carries the device's connection fields and its single project root.
    `tools.runs.train` SHALL auto-sync and forward the lifecycle when the
    configured hostname is not local.
18. Public remote commands SHALL use the same config as their first positional
    argument where required: `build_engine`, `kill`, `pull`, `status`, `tail`,
    and the training entry. Users SHALL NOT need to call `_ssh` or
    `_remote_sync` directly for the normal workflow.
19. `tools.runs.sync push|pull <user@host:path/>` SHALL synchronize metadata
    and config snapshots, excluding checkpoints, metrics, TensorBoard data,
    and other run outputs. `sync init-authoritative` SHALL record the host
    authorized to allocate local runs.
20. Checkpoint and result transfer SHALL use `tools.runs.pull`; process cleanup
    SHALL use `tools.runs.kill`; remote logs SHALL use `tools.runs.tail`.
22. Machine-identifying remote values (`ssh`, `os`, `hostname`, `root`) SHALL
    reside only in the git-ignored registry `configs/hosts/hosts.toml`, keyed by
    profile name. The repository SHALL ship `configs/hosts/hosts.example.toml`
    carrying placeholder values only, and SHALL NOT carry real values in any
    tracked file.
23. Resolving a remote host profile SHALL fail loudly — raising — when the
    registry file, the named profile, or any required field is absent or
    invalid. Resolution SHALL NOT fall back to local execution.
24. `tools.runs._remote_sync._auto_sync` SHALL include the host registry file in
    the path list it pushes, so the remote box resolves the same profile and its
    own `is_local_host` check succeeds. This single injection point covers both
    the initial full sync and the incremental sync; it is the sole sync path used
    in production (`tools.runs.train` and `tools.runs.build_engine` both route
    through it).
25. A remote device SHALL have exactly one project root, and it SHALL be the
    `root` value of that device's registry profile. Isolation between
    experiments SHALL be provided by cfg parameters and per-run
    `artifacts/<ts>_<NNN>_<label>/` directories, never by opening an additional
    project root on the device.

## Historical boundary

21. Pre-redesign `rNNN` and `sNNN` metadata remains historical evidence in
    `docs/5_history/runs_pre_redesign_2026_05_17.md`. Historical documents may
    describe the old commands as facts of their period, but LIVE documentation
    SHALL point to the interfaces above.

## References

- Training architecture: [`../training-architecture/spec.md`](../training-architecture/spec.md)
- Config schema: [`../config-schema/spec.md`](../config-schema/spec.md)
- Redesign record: [`../../../docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md`](../../../docs/superpowers/specs/2026-05-18-tools-runs-redesign-design.md)
- Development workflow: [`../../../CLAUDE.md`](../../../CLAUDE.md)
