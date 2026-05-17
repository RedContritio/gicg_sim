---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
parent: ./README.md
---

# DMC runs

> ⚠ DMC artifact 暂未进 [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md)。
> CLAUDE.md "Artifacts" 段 SHOULD pre-register;DMC Phase 3.4 smoke 走 ad-hoc
> naming(`202605HHMM_dmc_<label>`)。Stage 3 GPU train 启动前 SHOULD 补 r013+
> registry 行(per memory `project_v_phase2_eval_schema_gaps` 之类 silent fail 同样
> 暴露 registration 漏)。
>
> 本 dossier 列 Phase 3.4 smoke artifact 时间序;详细 per-run 数据见
> `training/paradigms/dmc/notes.md`(LIVE)+ artifact metrics.jsonl。

## 2026-05-14 Mac smoke runs(Phase 3.4)

| Artifact | Note |
|---|---|
| `202605140322_dmc_stage3_smoke` | early smoke iteration |
| `202605140326_dmc_stage3_smoke` | early smoke iteration |
| `202605140328_dmc_stage3_smoke` | early smoke iteration |
| `202605140341_dmc_stage3_smoke` | early smoke iteration |
| **`202605140344_dmc_stage3_smoke`** | **Phase 3.4 DONE marker** — 136 ep / 5035 frames / 549 train steps / loss 0.95→0.67 / vs F1-D2 WP 0→0.125 directional |
| `202605140449_dmc_stage3_smoke` | post-3.4 smoke |
| `202605141213_dmc_resume_test` | resume / restart smoke(see `configs/dmc_resume_test.toml`)|
| `202605141255_dmc_stage3_smoke` | post-resume smoke |
| `202605141311_dmc_stage3_smoke` | post-resume smoke |
| `202605141314_dmc_stage3_smoke` | post-resume smoke |
| `202605141351_dmc_stage3_smoke` | post-resume smoke |
| `202605141400_dmc_stage3_smoke` | post-resume smoke |
| `202605141918_dmc_stage3_smoke` | evening smoke |
| `202605141925_dmc_stage3_smoke` | evening smoke |
| `202605142140_dmc_stage3_smoke` | late-evening smoke |

## 2026-05-15 Phase 3.5 infra refactor smoke

| Artifact | Note |
|---|---|
| `202605151052_dmc_mp_smoke` | mp(multi-process)smoke after `_mp_` → single-entry merge |
| `202605151328_dmc_stage3_smoke` | post-3.5 Stage 3 smoke,NaN guard 启用 |
| `202605151345_dmc_stage3_smoke` | post-3.5 Stage 3 smoke,latest |

Phase 3.5 commit chain(per [`docs/5_history/dmc_phase35_infra.md`](../../5_history/dmc_phase35_infra.md)):

```
c67b9ba → 2da97a0 → a4e7181 → 18206bb → c675f34 → ce5049e → 4c43b92 →
3f3510c / 5ae3f7c → 2449ce6 / bb51d4d / 2278558 → d818ff3 → 29b3966
```

## Pending(Phase 3.2 / 3.4.5 / 3.5 train)

| Phase | Status | Note |
|---|---|---|
| 3.2 Cross-platform engine + adapter | pending Windows side | libgicg.dll + TCP socket |
| 3.4.5 CPU profile + 优化 | pending(Windows GPU 前必做) | per-actor fps target + X3D 优化 |
| 3.5 Stage 3 Windows train | pending(需先 3.2 + 3.4.5) | ~16-25h wall / 25-40 GPU-h;PASS WP ≥ 0.50 vs F1-D2 |
| 3.6 Stage 4 train | pending | 变 team size + asymmetric;~40-60 GPU-h |
| 3.7 Stage 5 train | pending | v_phase2 full deck(deferred prerequisite);~60-100 GPU-h |

每 stage 详 plan 见 [`training/paradigms/dmc/PLAN.md`](../../../training/paradigms/dmc/PLAN.md)。
PASS criteria 见 [`training/paradigms/dmc/notes.md`](../../../training/paradigms/dmc/notes.md) decision changelog 段。

## Run registry follow-up

Stage 3 GPU train 启动前,SHOULD 在 [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md)
登记:

- r013+(production-style DMC run)
- 或 s071+(若作 smoke / bench)
- Smoke artifact 是否需要追溯 register 由 user 决定;最低限度 Stage 3 production run 必须 register。
