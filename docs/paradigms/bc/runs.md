---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
parent: ./README.md
---

# BC runs

> Time-ordered BC era runs。详细数据见
> [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md)。BC paradigm 跨 PPO / AZ
> 两栈,run 在 [`../ppo/runs.md`](../ppo/runs.md) 和 [`../az/runs.md`](../az/runs.md)
> 也有列出 — 本 dossier 从 BC paradigm 视角组织。

## 2026-04-25 Stage 1 BC pretrain capacity sweep(s015-s017)

| Run | Cfg | 结果 |
|---|---|---|
| s015 | BC data gen Stage 1,50k decisions,F1-D2 teacher,opp mix=[F1-D2, F1-D1],teacher_side uniform | teacher self-wr=0.706 / tied_mask mean=2.83 / **hard ceiling 0.354** |
| s016 | d=256/h=2/10ep/soft | soft_match=34.3% FAIL |
| s016b | d=512/h=4/30ep/soft | soft_match=65.8% MARGINAL,首次 break hard ceiling |
| s016d | d=1024/h=4/60ep/soft | **soft_match=73.0%** MARGINAL,作 s017 fine-tune 起点 |
| s017 | s016d → PPO fine-tune | **F1-D2 = 0.500 PASS** n=16 / 0.500 PASS n=64 ladder |

**Batch verdict**: BC + PPO Stage 1 PASS;**+0.24 dominant lever**(s054 scratch peak ~0.11 vs s033 BC peak ~0.41 后续证实)。

## 2026-04-25 Stage 2 BC + PPO(s018-s020)

| Run | Cfg | 结果 |
|---|---|---|
| s018 | BC data gen Stage 2(obs_mask=['enemy_dice']),50k decisions | teacher 行为同 Stage 1(full-info snapshot/restore);obs_mask 只影响 student obs |
| s019 | s016d 同 arch,Stage 2 数据 | soft_match=66.2%(-7% vs Stage 1) |
| s020 | s019 → PPO fine-tune | **F1-D2 = 0.422 PASS n=16 / 0.531 PASS n=64** |

**Batch verdict**: partial-obs learnable via BC warm-start;~6-8% symmetric drop
quantifies enemy-dice info value。

## 2026-04-25 ~ 04-26 Stage 3 BC + PPO 4-factor ablation matrix(s021-s054)

详 [`../ppo/runs.md`](../ppo/runs.md) Stage 3 batch。BC 视角关键 cell:

| Cell | BC seed | PPO 4-factor | F1-D2 mean ± std |
|---|---|---|---|
| s022 BC pretrain | seed=0 | d=1024/h=4/60ep | soft_match=62.1% |
| s023-25 | s022 共享 BC,PPO seed {0,1,2} | multi-card masked | 0.073 ± 0.048 |
| s028-30 | s022 共享 BC | 1-card masked F1-D2 | 0.214 ± 0.095 |
| s033/39/40 | s022 共享 BC | **1-card fullobs F1-D2(best)** | **0.344 ± 0.062** |
| s054 | scratch(no BC)| 1-card fullobs | peak ~0.11 |

**Batch verdict**: BC factor +0.24 量化(s054 vs s033)。

## 2026-04-28 r009 BC pretrain + epoch sweep

| Run | Cfg | 结果 |
|---|---|---|
| r009_bc_data_gen_stage3 | 50k decisions Stage 3 | per `configs/r009_bc_data_gen_stage3.toml` |
| r009_bc_pretrain_stage3 | d=1024 / h=4 / 60ep / soft | full BC pretrain |
| r009_bc_eval_ep[0..6] | epoch ckpt vs F1-D2 ladder | **epoch_3 best vs F1-D2 = 0.75** |

ckpt sweep configs commit `1f180bd`。**epoch_3 选作 r010 init ckpt**(详下方)。

## 2026-04-28 r010 BC + AZ Stage 3 multi-seed

| Run | Seed | F1-D2 wr |
|---|---|---|
| r010_seed42 | 42 | 0.1875 |
| r010_seed43 | 43 | 0.125 |
| r010_seed44 | 44 | 0.1875 |

**Batch verdict**: F1-D2 = **0.167 ± 0.029**(远低 BC ckpt 自身 0.75 和 PPO BC+PPO
0.500)— **BC + AZ 路径在 GICG 上失败**;AZ training destroys BC signal。完整诊断
→ [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)。

## Production ckpt status

- **当前 production fallback**:r009 BC epoch_3 ckpt(详 r009 config + epoch sweep)
- **Replace 触发条件**:任何 RL paradigm 在 Stage 3 + v_phase2 上 multi-seed vs F1-D2
  ≥ 0.75 PASS。截至 2026-05-16 无 candidate。
- **DMC Phase 3.5 Stage 3 训完成**(pending)= 下一个候选 replace。
