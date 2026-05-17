---
date_range: 2026-04-25 ~ 2026-04-26
runs: s021-s054 (29 ablation, n=3 multi-seed per cell)
status: closure (BC→PPO ceiling 0.34, pivot AZ)
---

# Stage 3 BC→PPO Closure — 4-Factor Ablation Matrix

> Stage 3 (Curriculum: 加回卡牌) 在 BC→PPO pipeline 下的完整 ablation。
> 本文档沉淀 closure 数据点。下一步 (AZ 路线) 见
> [`../az_plans/r009_az_warmstart.md`](../az_plans/r009_az_warmstart.md)(已归档)。

## TL;DR

**F1-D2 ≥ 0.40 stricter 在当前 BC→PPO pipeline 物理不可达。**

最强配置 (1-card fullobs F1-D2 teacher) mean = 0.344 ± 0.062, peak = 0.406。
multi-card 配置全部 ≤ 0.10。

4-factor 中 BC warm-start (+0.24) 是 dominant lever,其余 (partial obs +0.13 / D3 teacher +0.10 / PPO oscillation ±0.10-0.15) 各自 marginal,且 best-of-each combo NOT additive。

## Run 矩阵

| Cell | runs | F1-D2 wr (mean ± std) |
|---|---|---|
| multi-card masked | s023, s024, s025 | 0.073 ± 0.048 |
| multi-card fullobs | s043, s046, s047 | 0.104 ± 0.045 |
| 1-card masked | s028, s029, s030 | 0.214 ± 0.095 |
| 1-card masked F1-D3 teacher | s036, s044, s045 | 0.318 ± 0.106 |
| 1-card fullobs F1-D2 | s033, s039, s040 | **0.344 ± 0.062** |
| 1-card fullobs F1-D3 (best-of-each combo) | s050, s051, s052 | 0.281 ± 0.078 (NOT additive!) |
| 1-card fullobs F1-D2 long (1000 iter) | s053 | wr 区间 [0.18, 0.42] (oscillation) |
| 1-card fullobs scratch (no BC) | s054 | peak ~0.11 (vs BC 0.34) |

## 4 个 contributing factors (量化)

| Factor | Effect on F1-D2 wr | 说明 |
|---|---|---|
| **BC warm-start** | **+0.24 (dominant)** | s054 scratch peak ~0.11 vs s033 BC peak ~0.41 |
| **partial obs** (mask enemy_dice) | +0.13 (1-card 下) | s028-30 vs s033/39/40 |
| **F1-D3 teacher** (vs D2) | +0.10 (masked-only) | masked-only,与 fullobs 互替 |
| **PPO oscillation** | ±0.10-0.15 noise | s053 1000 iter wr 在 [0.18, 0.42] 抖,不收敛 |

## Falsified hypotheses

- ❌ **soft target collapse**: hard target ablation (commit `4498f78`) 与 soft 同水平,不是 collapse 根因
- ❌ **PPO 500→1000 iter undertraining**: s053 长训 1000 iter 仍 oscillate,不是迭代不够

## Combo NOT additive

| 单 lever | 单点效应 |
|---|---|
| BC + partial obs (1-card masked) | 0.214 |
| BC + F1-D3 teacher (1-card masked D3) | 0.318 |
| BC + fullobs (1-card fullobs D2) | 0.344 |
| **BC + F1-D3 + fullobs (combined)** | 0.281 (低于 BC + fullobs 单独) |

D3 teacher 与 fullobs 在 1-card 下相互**互替而非叠加**。可能 root cause:F1-D3 teacher 提供的额外搜索深度信息在 fullobs 下变冗余。

## 决策

**不推 Stage 4,pivot 回 AZ 路线。**

详见 [adr-0008 paradigm pivot](../../2_decisions/adr-0008-rl_paradigm_pivot.md) 和
[stage3 closure status](../curriculum/stage3.md)(已归档)。

AZ 路线 next step 候选 (α/β/γ): [`../az_plans/r009_az_warmstart.md`](../az_plans/r009_az_warmstart.md)(已归档)。

## Artifacts

`artifacts/202604251133_*` ~ `artifacts/202604260143_*`,共 ~30 个 run 目录。

- BC data gen: ~5min each, ~1.5GB total (dataset.npz)
- BC pretrain: ~2-5min each, ~150MB (final.pt + metrics + summary)
- PPO finetune: ~10-20min each, ~50MB
- 总: ~3-5GB

不必清理,保留作 future re-eval 用 (e.g. 加 best-ckpt infra 后,可对这些 run 的 metrics.jsonl retrospect-pick best ckpt)。

## 关键 commit

- `85f74d7` ppo: Stage 3 pipeline (cards) single-seed inconclusive
- `a7110cd` ppo: Stage 3 multi-seed (n=3 PPO-fine-tune-seed) confirms F1-D2 FAIL
- `4498f78` ppo/bc_train: hard_target ablation flag (default soft preserved)
- `a618cf2` ppo: Stage 3 F1-D2 FAIL ablation configs (s026-s054)
- `11b56f7` docs: Stage 3 BC→PPO closure + pivot 回 AZ 路线

## 参考

- Memory: `project_stage3_full_diagnosis`, `project_stage3_single_seed`, `feedback_ppo_multiseed_required`
- Aggregate JSON: 在每组第一个 ckpt parent dir
- 工具: `tools/ppo_multiseed_aggregate.py`, `tools/ppo_bc_eval_probe.py`, `tools/ppo_eval_probe.py`
