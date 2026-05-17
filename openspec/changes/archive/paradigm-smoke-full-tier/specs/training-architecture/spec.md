---
last_updated: 2026-05-17
status: DELTA
schema_version: 0
change_id: paradigm-smoke-full-tier
delta_type: ADD
capability: training-architecture
---

# training-architecture spec delta — paradigm-smoke-full-tier

> Delta on top of `openspec/specs/training-architecture/spec.md`(LIVE)。
> Merge target:
> - § ADD invariant A1.6 — smoke_full tier 契约
> Archive-time merge per openspec-policy SOP(deferred to `/opsx:archive`)。

## ADD § A1.6 — smoke_full tier(完整 driver e2e + ckpt save/load)

**A1.6.1** Each paradigm `<X>` SHALL provide a second-tier smoke test
`training/tests/test_<X>_smoke_full.py` marked with
`@pytest.mark.smoke_full`,covering the full `tools.run` driver path
(NOT only Protocol-level forward + backward as A1.5 smoke does)。

**A1.6.2** smoke_full test SHALL subprocess-invoke `tools.run
<configs/<X>/smoke_full.toml>` to drive train loop to ≥ 100 step
(paradigm step_schedule terminus tuned via toml override to reach 100+
step within 8 min wall),then verify:

- `ckpt_<step>.pt` files actually written by `CheckpointManager.save`
  (≥ 2 ckpt files within the run)
- `latest.pt` symlink (copy) exists
- `metrics.jsonl` exists with at least one row

**A1.6.3** smoke_full test SHALL additionally invoke `tools.run --resume
<ckpt>` against the first ckpt produced in A1.6.2,verify:

- Subprocess exits 0(load + train continuation path functional)
- ≥ 1 new ckpt file written into the same artifacts dir after resume
  (CheckpointManager.init_artifacts_dir resume_from branch reuses parent dir)
- Functional verification only — no bit-identical weight comparison
  (per SF-102:rng state drift acceptable;target is load-path liveness)

**A1.6.4** smoke_full SHALL NOT be collected by default `pytest`:
`pyproject.toml [tool.pytest.ini_options].addopts` SHALL contain
`-m "not smoke_full"`。Opt-in via explicit `pytest -m smoke_full`。

**A1.6.5** smoke_full wall budget SHALL be ≤ 15 min per paradigm
(hard cap;target ≤ 8 min)。Full 5-paradigm sweep target ≤ 45 min。

**A1.6.6** Each paradigm `configs/<X>/smoke_full.toml` SHALL extend
`configs/<X>/smoke.toml` via `meta.extends = "smoke.toml"` and override
only:

- `[checkpoint] save_every` to short cadence(eg 30-100 step units)
- paradigm-specific terminus(`total_games` / `total_frames` /
  `n_iterations` / `n_epochs` / `total_iterations`)to reach ≥ 100 step
- `meta.run_label` to distinguish from smoke run

No new toml top-level sections;structural fidelity to base smoke.toml
preserved per `cfg-toml-restructure-paradigm-scoped` N6 hybrid form。

**A1.6.7** smoke_full tests MAY use `pytest.skip(reason=...)` if the
paradigm's `tools.run <smoke.toml>` path is blocked by a pre-existing
production bug outside this change scope(per SF-105)。The skip
message SHALL identify the bug + the follow-up change id required to
unblock. Skip is NOT a spec violation — it surfaces a contract gap
between paradigm production driver and the smoke_full tier。

## Cross-references

- Originating change → `openspec/changes/paradigm-smoke-full-tier/proposal.md`
- DECISIONS log → `openspec/changes/paradigm-smoke-full-tier/DECISIONS.md`
  - SF-101: subprocess `tools.run` (not in-process)
  - SF-102: functional resume verify, not bit-identical weight diff
  - SF-103: smoke_full toml uses `meta.extends`
  - SF-104: 8 min target / 15 min hard cap per paradigm
  - SF-105: 4/5 paradigm test files mark `pytest.skip` due to
    pre-existing production bugs (DMC only currently end-to-end pass)
- Predecessor change → `openspec/changes/core-network-generic-promotion/DECISIONS.md`
  - D-304: smoke single forward → upgraded to full driver episode in smoke_full
  - D-305: BC loss "不增长" → upgraded to strict decrease over 100 step in smoke_full
  - D-601: smoke_full tier added per user 2026-05-17 ask
- Related change → `openspec/changes/cfg-toml-restructure-paradigm-scoped/`
  - N6: hybrid TOML structure with `meta.extends`(used by smoke_full toml)
