"""tools.runs — Run metadata workflow + cross-machine sync.

Per clean-slate redesign (2026-05-18, docs/superpowers/plans/2026-05-18-
tools-runs-redesign-implementation.md). Run metadata + cfg snapshot +
ckpts all live under `artifacts/<ts>_<NNNNNN>_<label>/` (gitignored,
same lifecycle). CLI is the only sanctioned mutator — no hand-edit, no
parallel markdown registry.

Subcommands (post-redesign):

- ``tools.runs.train``      unified train entry (allocates NNN +
                            registers + auto-closes status)
- ``tools.runs.mark``       manual status transition (failed / killed)
- ``tools.runs.recover``    rebuild metadata.toml from on-disk artifacts
- ``tools.runs.list``       table view of all runs
- ``tools.runs.show``       detail dump of single run
- ``tools.runs.sync``       rsync wrapper for metadata and config snapshots
"""
