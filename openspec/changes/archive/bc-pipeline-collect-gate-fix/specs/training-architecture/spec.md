---
last_updated: 2026-05-17
status: DELTA
schema_version: 0
change_id: bc-pipeline-collect-gate-fix
delta_type: ADD
capability: training-architecture
---

# training-architecture spec delta — bc-pipeline-collect-gate-fix

> Delta on top of `openspec/specs/training-architecture/spec.md`(LIVE)+
> `openspec/specs/training-architecture/pipeline.md`(LIVE)。
>
> Merge target:
> - `pipeline.md` § 3 Core SHALL invariants — ADD #7 collect gate semantics
>
> Archive-time merge per openspec-policy SOP(deferred to `/opsx:archive`)。

## ADD § pipeline.md `## 3. Core SHALL invariants` invariant #7

**7. Collect phase gate SHALL be `plan.collect` only**

Driver loop SHALL gate the collect phase (`collector.collect(...)` +
`buffer.push(...)` + `state.after_collect(...)`) by `StepPlan.collect`
alone。

Driver SHALL NOT additionally gate on `plan.n_episodes > 0` (or similar
"non-zero unit count" checks)。`n_episodes` is a **collector-internal
contract** carrying paradigm-aware metadata(episode-driven paradigm
emit the actual episode count;dataset-driven paradigm such as BC emit
`0` truthfully since they have no episode concept)。

Rationale:treating `n_episodes > 0` as a driver-side gate breaks
dataset-driven paradigm whose `step_schedule` legitimately emit
`StepPlan(collect=True, n_episodes=0)` (their `DatasetCollector.collect`
ignores `n_units` per docstring contract and pushes the full static
dataset on the first invocation)。Pre-fix, BC's collector was never
called → buffer empty → all train batches `break` on
`len(buffer) < batch_size` → `train_steps = 0` despite ckpts being
written. The redundant gate had no purpose for episode-driven paradigm
(their `step_schedule` already emit `collect=False` at terminus) and
silently de-trained dataset-driven paradigm.

## Cross-references

- Originating change → `openspec/changes/bc-pipeline-collect-gate-fix/proposal.md`
- Predecessor change → `openspec/changes/archive/bc-smoke-dataset-fixture/design.md`
  - Discovered this bug during fixture work (see Surprises § first bullet);
    deferred fix to this follow-up per strict scope。
- Affected source → `training/core/pipeline.py:83`(gate relax to
  `if plan.collect:`)
- Affected test → `training/tests/test_bc_smoke_full.py`(metrics
  assertion `train_steps > 0` locks regression)
- Affected paradigm contract → `training/paradigms/bc/paradigm.py:122-158`
  `step_schedule` emits `n_episodes=0` truthfully;
  `training/paradigms/bc/collector.py:62-102` `DatasetCollector.collect`
  ignores `n_units` and one-shot pushes the full dataset
- Non-BC paradigm regression analysis → all 4 RL paradigm
  (AZ / DMC / PPO / CFR) emit `n_episodes > 0` whenever `collect=True`,
  so the gate relax is bit-identical for them(详 design.md
  "Non-BC paradigm regression analysis" 表)
