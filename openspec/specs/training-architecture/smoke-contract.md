---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: training-architecture
subtopic: smoke-contract
---

# Training Architecture — Smoke 契约 + paradigm-specific probe

> 本 subtopic 承载 paradigm-agnostic smoke test contract:每 paradigm
> 必须提供 `test_<paradigm>_smoke.py` 实施 zero-startup / mini-train /
> eval probe / paradigm-specific invariant 共 5 个 SHALL 子条件。详细
> SHALL 锚定见 [`./invariants.md` (#18 smoke 契约)](./invariants.md) +
> [`./paradigm-onboarding.md`](./paradigm-onboarding.md) §1.2(接入 SOP)。

## 1. 章节由来

Added by `core-network-generic-promotion` (archived 2026-05-17),配合
`invariants.md` SHALL 18 smoke test contract 落地。每 paradigm
`training/tests/test_<paradigm>_smoke.py` with `@pytest.mark.smoke`
SHALL 满足以下契约 — paradigm 接入 merge gate。

## 2. 通用 smoke 5 条契约

1. **从零启动**:无 ckpt 依赖,从 random init 跑
2. **mini-train**:真走 `collector → buffer → forward → backward →
   optimizer.step`,SHALL NOT stub training loop
3. **eval probe**:训练后 ≥ 1 局 e2e episode,terminal reward 在
   `[-1, +1]` 流通
4. **paradigm-specific invariant**(详 §3)
5. **Wall time ≤ 2min**:CI / pre-commit 友好(默认 smoke tier;`smoke_full`
   tier 5-15min,opt-in via `-m smoke_full`,见 `AGENTS.md`)

## 3. 5 paradigm-specific probe

| Paradigm | Smoke-specific invariant |
|---|---|
| **AZ**  | MCTS `visit_counts > 0` for ≥ 1 expanded node + value `∈ [-1, 1]` |
| **BC**  | cross_entropy loss decrease(初始 random vs 100 step training) |
| **DMC** | Q-value finite + ε-greedy 在 `ε=1` 时全 random(non-deterministic) |
| **CFR** | strategy distribution sums to 1(per-infoset)+ regret `< ∞` |
| **PPO** | clip ratio in `[1-ε, 1+ε]` + advantage normalized(mean ≈ 0, std ≈ 1) |

## 4. smoke_full tier 协议(A1.6 7 子约束)

> Added by `paradigm-smoke-full-tier`(archived 2026-05-17),配合
> `invariants.md` SHALL #18 two-tier 扩展。smoke_full SHALL 满足以下
> 7 子约束 — opt-in 全 train(5-15min/paradigm),run before big release /
> cfg schema change / network architecture change。

**A1.6.1** Each paradigm `<X>` SHALL provide a second-tier smoke test
`training/tests/test_<X>_smoke_full.py` marked with
`@pytest.mark.smoke_full`,covering the full `tools.runs.train` driver path
(NOT only Protocol-level forward + backward as default smoke does)。

**A1.6.2** smoke_full test SHALL subprocess-invoke `tools.runs.train
<configs/<X>/smoke_full.toml>` to drive train loop to ≥ 100 step
(paradigm step_schedule terminus tuned via toml override to reach 100+
step within 8 min wall),then verify:

- `ckpt_<step>.pt` files actually written by `CheckpointManager.save`
  (≥ 2 ckpt files within the run)
- `latest.pt` symlink (copy) exists
- `metrics.jsonl` exists with at least one row

**A1.6.3** smoke_full test SHALL additionally invoke `tools.runs.train --resume
<ckpt>` against the first ckpt produced in A1.6.2,verify:

- Subprocess exits 0(load + train continuation path functional)
- ≥ 1 new ckpt file written into the same artifacts dir after resume
  (`CheckpointManager.init_artifacts_dir` resume_from branch reuses
  parent dir)
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
paradigm's `tools.runs.train <smoke.toml>` path is blocked by a pre-existing
production bug outside this change scope(per SF-105)。The skip
message SHALL identify the bug + the follow-up change id required to
unblock。Skip is NOT a spec violation — it surfaces a contract gap
between paradigm production driver and the smoke_full tier。

## 5. Smoke vs smoke_full tier 区分(quick reference)

- `@pytest.mark.smoke` — 默认 smoke(≤ 60s/paradigm,CI / pre-commit
  友好,5 paradigm 全 collected),由 §2 5 条契约 + §3 paradigm-specific
  invariant 治理
- `@pytest.mark.smoke_full` — opt-in 全 train(5-15min/paradigm,real
  100-step train + auto-save ckpt + resume verify via `tools.runs.train` driver
  e2e),通过 pyproject `addopts -m "not smoke_full"` 默认 exclude;由 §4
  7 子约束 A1.6.1-A1.6.7 治理

开发时的运行要求见 `AGENTS.md`。

## 6. Cross-references

- 主 spec → [`./spec.md`](./spec.md)
- SHALL 锚定 → [`./invariants.md` (#18 smoke 契约 two-tier)](./invariants.md)
- Paradigm 接入 SOP → [`./paradigm-onboarding.md`](./paradigm-onboarding.md)
- File layout 约定 → [`../openspec-policy/file-layout.md`](../openspec-policy/file-layout.md)
- Originating changes:
  - default smoke 契约(§2 + §3)→
    [`../../changes/archive/core-network-generic-promotion/`](../../changes/archive/core-network-generic-promotion/)
  - smoke_full tier(§4)→
    [`../../changes/archive/paradigm-smoke-full-tier/`](../../changes/archive/paradigm-smoke-full-tier/)

### 6.1 smoke_full DECISIONS 索引

A1.6 7 子约束的决策依据(per archive `paradigm-smoke-full-tier/DECISIONS.md`):

- **SF-101** — subprocess the production training entry, currently `tools.runs.train`, not an in-process driver call
  (避免 sys.path / global state 污染,与 production 调用 1:1)
- **SF-102** — functional resume verify,not bit-identical weight diff
  (rng state drift acceptable,bit-identical 会 flaky)
- **SF-103** — smoke_full toml 用 `meta.extends` 继承 smoke.toml
  (per `cfg-toml-restructure-paradigm-scoped` hybrid structure)
- **SF-104** — 8 min target / 15 min hard cap per paradigm
- **SF-105** — the original change allowed `pytest.skip` for named external
  blockers; those blockers were later fixed and all five smoke_full tests are
  now collected when the marker is explicitly selected
- **SF-106** — smoke_full ckpt artifacts_root SHALL be `--override
  checkpoint.artifacts_root=<tmp_path>` 隔离(pytest tmp_path 自动 cleanup +
  多次 test 不互相 stomp + production artifacts 不被 test 数据污染)
- **D-304 / D-305 closure** — parent change deferred items 通过 smoke_full
  full driver episode + 100-step BC loss probe closure

## 7. Status

- **Created**:2026-05-17(split from `paradigm-onboarding.md` §8 by
  parent change fixup — paradigm-onboarding.md 458 line 超 file-layout
  §1.1 subtopic ≤ 400 cap)
- **Revised**:2026-05-17(`paradigm-smoke-full-tier` archived):§4
  smoke_full tier 7 子约束 A1.6.1-A1.6.7 落地;§5 tier 区分 quick reference;
  §6.1 DECISIONS 索引(SF-101..106 + D-304/305 closure) + Cross-references
  多 originating change link
- **Version**:0(增量加 A1.6,无 schema breaking 修改)
- **Expected revision triggers**:
  - 第 6 paradigm 接入完成 → §3 表格加该 paradigm probe 行 + §4 smoke_full
    协议沿用(toml extends + skip 灵活性)
  - smoke 契约 SHALL 条件变化(invariants.md #18 修订)→ §2 / §4 同步
  - smoke_full tier 协议演化 → §4 A1.6.* 同步
