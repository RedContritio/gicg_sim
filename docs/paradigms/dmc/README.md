---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
paradigm: dmc
---

# DMC paradigm dossier

> **Status**: **ACTIVE**
>
> **One-line verdict**: Phase 3.4 Mac smoke verified 2026-05-14(136 ep / 5035 frames /
> loss 0.95→0.67,vs F1-D2 WP 0→0.125 directional);Phase 3.5 infra refactor ship 2026-05-15;
> Stage 3 Windows GPU train pending(per `training/paradigms/dmc/notes.md` LIVE)。
> **41 项 review critique** 留 in [`docs/5_history/reviews/dmc_review.md`](../../5_history/reviews/dmc_review.md),含 A.3 PASS 标准
> ≥0.50 vs 同 setup 实测 RL 上限 0.271 ± 0.078 — 立项即过乐观,需 closure review。

## Overview

DMC(Deep Monte-Carlo)是 2026-05-12 以来 GICG RL 新主线,以 DouZero 路线为参考。
核心轨迹:

1. **设计落定**(2026-05-12):8 个 decision 全 settled — A1 logit-as-Q / 30/30/10/30
   opp mix / 3 stages(3/4/5)/ asymmetric Stage 3 / per-stage PASS WP ≥ 0.50 /
   Windows native + libgicg.dll / in-repo `training/dmc/` / lazy periodic eval / 充分 CPU 优化。
2. **Phase 3.1 DMC core**(2026-05-14):~1280 LOC across 13 files,Mac smoke verified。
3. **Phase 3.3 eval 协议**(2026-05-14):gen_eval_scenarios + periodic_eval,smoke 4 round 验证。
4. **Phase 3.4 Mac smoke + eval verify**(2026-05-14 03:44):136 ep / 5035 frames /
   549 train steps,loss 0.95→0.67,vs F1-D2 WP 0→0.125 directional。
5. **Phase 3.5 infra refactor**(ship 2026-05-15):`tools/remote/` SSH 链 +
   `tools/eval/` paradigm-agnostic dispatcher + `training/dmc/` 合并 single/mp entry +
   NaN guard。12 task ✓,详 [`docs/5_history/dmc_phase35_infra.md`](../../5_history/dmc_phase35_infra.md)。
6. **2026-05-14 dmc_review.md 41 项 critique**:A(paradigm 错配)/ B(layout 破坏)/
   C(代码 hard bug)/ D(eval noise)/ E(算力账目)/ F(closure / ablation 缺)。

## Active questions(尚未解决)

| Critique | Status |
|---|---|
| A.3 Stage 3 PASS WP ≥ 0.50 vs 同 setup 实测 RL 上限 0.271 ± 0.078 — 过乐观 | OPEN(closure 决策 pending Stage 3 GPU train) |
| C.x 4+ hard bugs 是否 Phase 3.5 已 fix | partial(NaN guard fix ✓,其他列在 review 待 cross-ref) |
| Cross-platform engine + adapter(Phase 3.2)| PENDING(Windows side libgicg.dll + TCP socket) |
| CPU profile + 优化(Phase 3.4.5)| PENDING(Windows GPU 前必做) |
| Stage 3 GPU train(Phase 3.5)| PENDING(需 3.2 + 3.4.5) |

## Verdict tree

```
Phase 3.1-3.3 (设计 + core + eval 协议)
└── Mac smoke OK ✓

Phase 3.4 (Mac smoke + eval verify, 2026-05-14)
└── 136 ep / 5035 frames / loss 0.95→0.67 / WP 0→0.125 directional
    → "学到 something" 初步 verify,但 evidence light

Phase 3.5 infra (2026-05-15)
└── tools refactor + NaN guard + paradigm-agnostic eval ✓

Phase 3.2 Windows engine + 3.4.5 CPU profile (pending)
└── Stage 3 GPU train (pending)
    └── PASS WP ≥ 0.50 vs F1-D2 → DMC paradigm ACCEPT
    └── FAIL → close paradigm,review A.3 项 + 切下一选项
```

## Key data points(Phase 3.4 Mac smoke)

| Metric | Value |
|---|---|
| Episodes | 136 |
| Frames | 5035 |
| Train steps | 549 |
| Loss | 0.95 → 0.67 |
| vs F1-D2 WP | 0 → 0.125 directional |
| Wall(Mac CPU) | 5 min |

⚠ Light evidence — single seed,n=128 swap evaluation 但 directional only。
PASS criterion(WP ≥ 0.50)not yet 测;Stage 3 GPU train 才 真正 stress test。

## Subdirectories

- [Runs](./runs.md) — Phase 3 smoke / pilot artifact 列表(未进 registry)
- [Postmortems](./postmortems.md) — `dmc_review.md` 41 项 critique 入口

(无 ablations.md / architecture.md — DMC paradigm 早期,architecture
"reuse AZ ActorCritic + logit-as-Q" 是 single decision A1;若未来 stage 3 train
后有 ablation,可补)

## Cross-references

**Archived OpenSpec changes**: 暂无 DMC-specific archived change。DMC paradigm 决策
落 `training/paradigms/dmc/notes.md` decision changelog 段(LIVE working notes),未走 OpenSpec
proposal 流程。**若 Stage 3 GPU train PASS,SHOULD 走 ADR 落 paradigm decision**。

**Frozen history**:

- [`docs/5_history/reviews/dmc_review.md`](../../5_history/reviews/dmc_review.md) —
  **5/14 41 项 critique 全文**(canonical critique 来源)
- [`docs/5_history/dmc_phase35_infra.md`](../../5_history/dmc_phase35_infra.md) —
  Phase 3.5 infra refactor design(archived 2026-05-16,P1-T7)
- [`docs/5_history/dmc_phase35_infra_impl/`](../../5_history/dmc_phase35_infra_impl/) —
  Phase 3.5 infra 实施 plan(P1-T7 archived,含 NaN root cause / eval / view / remote 子 plan)

**LIVE working notes**(不复制内容,只 link):

- [`training/paradigms/dmc/notes.md`](../../../training/paradigms/dmc/notes.md) —
  **LIVE working notes**(not archived);decision changelog + Phase 进度 + CPU 优化目标 / Stage
  PASS criteria。本 dossier link 它而非 mirror。
- [`training/paradigms/dmc/PLAN.md`](../../../training/paradigms/dmc/PLAN.md) — Phase plan(LIVE)

**Run registry**:

⚠ **DMC artifact 暂未进 `docs/5_history/runs_pre_redesign_2026_05_17.md`**(per CLAUDE.md "Artifacts" 段 SHOULD
register before launch,但 DMC Phase 3.4 smoke 走 ad-hoc artifact naming `202605140344_dmc_stage3_smoke`)。
完整 artifact 列表见 [`./runs.md`](./runs.md)。

**Memory**:

- `project_rl_routes_closure_2026_05_12` — user 评估 DMC vs ADR-0009/0010 closure 集合,
  DMC 作新主线
- `project_typed_obs_ckpt_break` — ADR-0019 §B.3a 前所有 ckpt 不兼容,DMC ckpt 受影响
- `project_v_phase2_eval_schema_gaps` — `eval_service_schema.json` pool/deck_padding
  字段补丁(DMC v_phase2 eval 配套)

**Code**:

- [`training/paradigms/dmc/`](../../../training/paradigms/dmc/) — DMC adapter
  (P3-B ship,paradigm.py + collector.py + buffer.py + loss.py + network.py;
  FU-W4-DMC-pt2 后 `legacy/` retired via `73c6ed7`)
- [`training/paradigms/dmc/paradigm.py`](../../../training/paradigms/dmc/paradigm.py) — DMCParadigm 入口
- [`training/paradigms/dmc/collector.py`](../../../training/paradigms/dmc/collector.py) — actor / async collector
- [`tools/remote/`](../../../tools/remote/) — Windows GPU box SSH 链(paradigm-agnostic)
- [`tools/eval/`](../../../tools/eval/) — paradigm-agnostic eval dispatcher
