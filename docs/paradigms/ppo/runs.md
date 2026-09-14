---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# PPO runs

> Time-ordered run list, batched by paradigm milestone. 详细 per-row 数据
> 在 [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md)(canonical source);
> 本 dossier 只列 batch verdict + 关键 run。

## 2026-04-19 ~ 04-21 backend bench + obs ablation(r001-r006)

| Run | Cfg | Verdict |
|---|---|---|
| s001 / s002 | Python vs Go backend, random_1v1 100g | Go -19% wall, validated for production |
| r001 | randteam2 400g baseline | g400 gauntlet mcts_200=0.55(C1v7 era benchmark) |
| r002 | fast lambda_anneal=400(vs default 1500) | mcts_200=0.30(fast anneal worse,see memory `project_r002_fast_anneal_worse`)|
| r003 | r002 + char_skill_refs obs + expand_union_k=3 | mcts_200=0.25(进一步退步;train loss 改善但 argmax wr 反相关) |
| r004 | slow anneal + K=3 | mcts_200=0.40(slow > fast 确认) |
| r005A | slow no-union (K=1) | mcts_200=0.45(K=3 净负 0.05) |
| r006 | r005A − char_skill_refs obs | mcts_200=0.40(char_skill_refs +0.05) |

**Batch verdict**: obs / anneal ablation 量化各 lever 贡献,完整分析见
[`docs/5_history/ablations/r001_r006_ablation.md`](../../5_history/ablations/r001_r006_ablation.md)。
r001 mcts_200=0.55 是 C1v7 era 最强 baseline。

## 2026-04-23 ~ 04-24 CFR detour(r007 killed / r008 CFR)

- r007: 1500g slow long-train,I5 deadlock killed at g1247(arena collapse trajectory)。
- r008: paradigm change Deep CFR(详 [`../cfr/`](../cfr/));非 PPO,记此为时间顺序。

## 2026-04-24 ~ 04-25 PPO Stage 0/1 baseline + diagnostics(s008-s014)

| Run | Cfg | F1-D2 wr | Verdict |
|---|---|---|---|
| s008 | Stage 0 fix_dice mirror | 0.875 / 0.125 / 0.406(3 seed) | indicative;single seed 不可信 |
| s009 | Stage 1 stochastic dice | 0.000 | policy 塌陷 Tune-heavy |
| s010 | s009 + 4× iter | 0.062 | iter 不是根因,反退步 |
| s011 | terminal=10 + value_coef=0.1 | 0.000 | value 量级修复,policy 仍 collapse |
| s012 | fix opp = F1-D1 | 0.000 | breakthrough — policy 学到 attack 但 generalize FAIL |
| s013 | s012 + 2000 iter | 0.000 | opponent overfit |
| s014 | mixed opp F1-D1+F1-D2 | 0.062(n=64) | Stage 1 pure PPO 路径走完 FAIL |

**Batch verdict**: pure PPO Stage 1 5 pipeline 全 FAIL → 触发
ADR-0008 paradigm pivot(BC warm-start)。详
[`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md) §诊断时间线。

## 2026-04-25 BC warm-start + Stage 1/2 PASS(s015-s020)

| Run | Cfg | 结果 |
|---|---|---|
| s015 | BC data gen Stage 1 (50k decisions, F1-D2 teacher) | hard ceiling 0.354 / tied_mask mean 2.83 |
| s016 / s016b / s016d | BC pretrain net size sweep | d=1024/h=4/60ep soft_match=73% best |
| s017 | s016d → PPO fine-tune Stage 1 | **F1-D2 = 0.500 PASS** |
| s018 | BC data gen Stage 2 | tied_mask mean 2.83(类似 Stage 1) |
| s019 | BC pretrain Stage 2 | soft_match 66.2%(-7% vs Stage 1,info loss 量化) |
| s020 | BC → PPO Stage 2 | **F1-D2 = 0.531 PASS** |

**Batch verdict**: BC warm-start +0.24 dominant lever 确认。

## 2026-04-25 ~ 04-26 Stage 3 ablation matrix(s021-s054)

29 ablation × n=3 multi-seed,4 factor matrix(BC / partial obs / teacher / oscillation)。

| Cell | runs | F1-D2 mean ± std |
|---|---|---|
| multi-card masked | s023-s025 | 0.073 ± 0.048 |
| multi-card fullobs | s043/s046/s047 | 0.104 ± 0.045 |
| 1-card masked | s028-s030 | 0.214 ± 0.095 |
| 1-card masked F1-D3 teacher | s036/s044/s045 | 0.318 ± 0.106 |
| **1-card fullobs F1-D2 (best)** | s033/s039/s040 | **0.344 ± 0.062** |
| 1-card fullobs F1-D3 combo | s050-s052 | 0.281 ± 0.078 (NOT additive!) |
| 1-card fullobs long 1000 iter | s053 | [0.18, 0.42] oscillation |
| 1-card fullobs scratch (no BC) | s054 | peak ~0.11 |

**Batch verdict**: F1-D2 ≥ 0.40 stricter 物理不可达 → ADR-0009
curriculum closure。完整 ablation 详
[`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md)。

## Closure(2026-04-26)

PPO paradigm 在 Stage 3 closure → pivot AZ(详 [`../az/`](../az/))+ BC
作 production fallback(详 [`../bc/`](../bc/))。后续 PPO run 无 production 价值;
若要复盘历史 run / 决策上下文 → [`docs/5_history/eras/ppo_pre_az/`](../../5_history/eras/ppo_pre_az/)。
