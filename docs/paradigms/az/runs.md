---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# AZ runs

> Time-ordered run list,详细数据见
> [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md)。

## Pre-registry baselines(2026-04-18)

| Artifact dir | Cfg | g400 mcts_200 | Note |
|---|---|---|---|
| `202604180500_az_c1v7` | shipped_1v1 pre-rename(team_size=1 random)| 0.45 | First ship of C1v7(sid pinning + struct_readout) |
| `202604181653_az_c3` | shipped_2v2 pre-rename(team_size=2 fixed)| 0.45(g200) | First team_size=2 verification,disjoint_teams=true |

## 2026-04-19 ~ 04-21 C1v7 era obs/anneal ablation(r001-r006)

详 [`../ppo/runs.md`](../ppo/runs.md) — 这批 run 同时是 PPO baseline 也是 AZ era
benchmark(C1v7 + IS-MCTS),按时间顺序在 PPO dossier 中列出。代表:r001
mcts_200=0.55 是 C1v7 era 最强 baseline。

## 2026-04-26 AZ Stage 0-2 baseline(s055-s063)

| Run | Cfg | mcts_200 wr | F1-D2 backfill |
|---|---|---|---|
| s055-s057 | Stage 0 fix_dice mirror,3 seed | 0.69/0.56/0.38 | — |
| s058-s060 | Stage 1 stochastic dice,3 seed | 0.31/0.50/0.31 | — |
| s061-s063 | Stage 2 partial obs(mask enemy_dice)| 0.31/0.50/0.31 | 0.19/0.12/0.12 |

**Batch verdict**: Stage 0-2 vs random / mcts_200 PASS;F1-D2 ladder backfill 显示
Stage 2 跨 seed F1-D2 ≤ 0.25。AZ Stage 0-2 与 PPO BC→PPO Stage 0-2 大致同强。

## 2026-04-26 AZ Stage 3 1-card baseline(s064-s066)

| Run | seed | mcts_200 wr | F1-D2 wr |
|---|---|---|---|
| s064 | 42 | 0.125 | 0.0625 |
| s065 | 43 | 0.500 | 0.0625 |
| s066 | 44 | 0.1875 | 0.1875 |

**Batch verdict**: F1-D2 = **0.104 ± 0.072** — Stage 3 pure self-play 不学得到,
与 PPO 1-card 0.214 ± 0.095 反向(AZ 弱于 PPO 同 stage)。

## 2026-04-28 AZ Stage 3 BC warm-start(r010)

| Run | seed | F1-D2 wr |
|---|---|---|
| r010_seed42 | 42 | 0.1875 |
| r010_seed43 | 43 | 0.125 |
| r010_seed44 | 44 | 0.1875 |

**Batch verdict**: F1-D2 = **0.167 ± 0.029**,远低 0.40 stricter,也远低
BC ckpt 自身 0.75。**AZ training destroys BC signal**:不同于 PPO BC+PPO 0.500,
AZ value head 训练 / determinize / self-play 联合摧毁 teacher prior。
完整诊断 → [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)。

## 2026-04-28 AZ Stage 3 multi-card(s067)

| Run | seed | F1-D2 wr |
|---|---|---|
| s067_seed42 | 42 | 0.000 |
| s067_seed43 | 43 | 0.125 |
| s067_seed44 | 44 | 0.0625 |

**Batch verdict**: 3-card pool F1-D2 = **0.062 ± 0.062** — 与 PPO multi-card
0.104 一致量级。combinatorial breadth 是 paradigm-independent cliff。

## 2026-04-28 AZ Stage 3 D4 asymmetric mirror-break(s068)

asymmetric teams(team_0=赤蝶, team_1=墨客)pure self-play:

| Run | seed | F1-D2 wr |
|---|---|---|
| s068_seed42 | 42 | 0.1875 |
| s068_seed43 | 43 | 0.375 |
| s068_seed44 | 44 | 0.250 |

**Batch verdict**: F1-D2 = **0.271 ± 0.094**,+0.167 vs s064-66 mirror baseline。
seed43 = 0.375 first crossing PPO BC ceiling 0.344。**Mirror Nash 锁死是 plateau
主因之一** 假设确认。触发 ADR-0010 partial reopen。

## 2026-04-28 AZ Stage 3 D4 more_rollouts probe(s069 — CANCELLED)

| Run | seed | Status |
|---|---|---|
| s069_seed42 | 42 | **pending → cancelled** |
| s069_seed43 | 43 | **pending → cancelled** |
| s069_seed44 | 44 | **pending → cancelled** |

**Batch verdict**: user-killed at seed42 → 优先 ADR-0011 改造(pool versioning)。
后续 user 2026-05-12 评估 closure 集合时 explicit 把 s069 计入 cancelled。
详 memory `project_rl_routes_closure_2026_05_12`。

## 2026-04-28 r010 multi_seed n=3 派生(seed43 / seed44)

详 [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md) `r010_az_bcwarmstart_stage3_seed{43,44}` 两行
(registry 用 r010 label × 3 seed,而非 r011/r012 命名约定)。
seed43:F1-D2=0.125;seed44:F1-D2=0.1875。
合并 r010 三 seed mean = 0.167 ± 0.029,与 BC ckpt 单独 vs F1-D2=0.75 对比,**BC 策略被 AZ self-play distribution shift 摧毁**。
paradigm 边界与 BC 重叠,详 [`../bc/runs.md`](../bc/runs.md)。

## 2026-05-12 v_phase2 凯亚 mirror probe(s070)

| Run | Verdict |
|---|---|
| s070 | undertrained — no learning signal(200g + n_rollouts=100 太少;附带 fix `eval_service_schema.json` pool/deck_padding 字段)|

**Batch verdict**: v_phase2 池上 AZ 需 ≥ 1000g + asymmetric;此后 paradigm
主线让位 DMC(详 [`../dmc/`](../dmc/))。
