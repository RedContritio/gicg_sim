"""tools.runs — Run metadata workflow + cross-machine sync.

Per OpenSpec change `core-network-generic-promotion` Phase 5
(spec `tools-layout/spec.md` invariants T1-T5).

Run metadata lives in `artifacts/runs/<run_id>.toml` (gitignored,
same lifecycle as ckpt / replays). CLI is the only sanctioned
mutator — no hand-edit, no parallel markdown registry.

Subcommands:

- ``tools.runs.register``  start a run record (status=pending)
- ``tools.runs.complete``  finalize a run record (status=done|failed|killed)
- ``tools.runs.list``       table view (replaces docs/4_runs/registry.md)
- ``tools.runs.show``       detail dump of single run
- ``tools.runs.sync``       rsync wrapper, pull/push only runs/*.toml
"""
