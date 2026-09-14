> **ARCHIVED 2026-05-16(P1-T7)** — Stage 3 PPO closure 0.344 / AZ pure 0.104 / AZ+BC 0.167(stricter ≥0.40 FAIL),curriculum CLOSED per ADR-0009/0010,详见 [`plan.md`](plan.md) 顶部 note。

---

---
stage: 3
status: PPO closure (ceiling 0.34) + AZ pure self-play 不能突破 — 都 stricter FAIL
last_updated: 2026-04-26
runs: s021-s054 (PPO closure ablation), s064-s066 (AZ 1-card multi-seed)
---

# Stage 3 — 加回卡牌

## 双栈 verdict

**PPO BC→PPO 路线**: ceiling F1-D2 = 0.34 (1-card fullobs best),物理不可达 ≥0.40 stricter。
**AZ pure self-play 路线**: F1-D2 = 0.104 ± 0.072 — **比 PPO 还弱**,远不突破 PPO ceiling。

**结论**: AZ pure self-play 不能突破 PPO ceiling。突破需 BC warm-start (paradigm pivot 文献 P0-1 预测)。

## Spec

Stage 2 同 + 小卡池 + hand (隐藏) + deck (隐藏)。

## PPO 路线 closure (s021-s054, 29 ablation, n=3 multi-seed)

| 实验 | F1-D2 mean ± std |
|---|---|
| multi-card masked (s023-25) | 0.073 ± 0.048 |
| multi-card fullobs (s043/46/47) | 0.104 ± 0.045 |
| 1-card masked (s028-30) | 0.214 ± 0.095 |
| 1-card masked F1-D3 teacher (s036/44/45) | 0.318 ± 0.106 |
| **1-card fullobs (s033/39/40)** | **0.344 ± 0.062** |
| 1-card fullobs F1-D3 teacher (s050-52) | 0.281 ± 0.078 (NOT additive) |

**4 个 contributing factors:** BC warm-start +0.24 / partial obs +0.13 / F1-D3 teacher +0.10 / PPO oscillation ±0.10-0.15.

**Falsified:** soft target collapse / PPO 500→1000 iter undertraining.

## AZ pure self-play 路线 (s064-s066, 1-card masked, n=3)

完整 ladder:

| seed | random | mcts_50 | mcts_100 | mcts_200 | F1-D1 | F1-D2 | F1-D3 |
|---|---|---|---|---|---|---|---|
| s064 (42) | 0.6875 | 0.5625 | 0.500 | 0.125 | 0.250 | 0.0625 | 0.0625 |
| s065 (43) | 0.9375 | 1.000 | 0.9375 | 0.500 | 0.5625 | 0.0625 | 0.0625 |
| s066 (44) | 0.875 | 1.000 | 0.625 | 0.1875 | 0.500 | 0.1875 | 0.125 |

| baseline | mean ± std (n=3) |
|---|---|
| vs random | **0.833 ± 0.130** |
| vs mcts_pure_50 | 0.854 ± 0.253 |
| vs mcts_pure_100 | 0.688 ± 0.225 |
| vs mcts_pure_200 | 0.271 ± 0.201 |
| vs F1-D1 | 0.438 ± 0.166 |
| **vs F1-D2** | **0.104 ± 0.072** |
| vs F1-D3 | 0.083 ± 0.036 |

训练 wall ~22min per seed。配置 `configs/s064-s066_az_stage3_1card_*.toml`
(Stage 2 spec + card_pool=["测试卡_碎片"])。

## AZ vs PPO Stage 3 直接对照

| | F1-D2 | 差距 |
|---|---|---|
| PPO 1-card masked (s028-30) | 0.214 ± 0.095 | — |
| **AZ 1-card masked (s064-66)** | **0.104 ± 0.072** | **AZ -0.11** |
| PPO 1-card fullobs best (s033/39/40) | 0.344 ± 0.062 | AZ -0.24 |

AZ pure self-play **strictly worse** than PPO BC→PPO at Stage 3。这与 paradigm pivot 文献预测一致 — BC warm-start 是 dominant lever (+0.24)。

## Go/No-go — dual judge

| 判据 | PPO 路线 | AZ 路线 |
|---|---|---|
| curriculum_plan 官方 (vs random ≥ 0.65) | PASS | PASS (0.833,但 s064=0.69 接近阈值) |
| F1-D2 stricter (≥ 0.40) | **FAIL** (ceiling 0.34) | **FAIL** (0.104) |

## 决策 (2026-04-26 更新)

**Stage 3 vs F1-D2 ≥ 0.40 在 pure self-play 路径下不可达**,与 PPO BC→PPO ceiling (0.34) 同结论但更弱。Stage 0/1/2/3 vs F1-D2 plateau 在 ~0.10-0.15,**self-play collapse 是结构性问题**,不是 stage 难度。

**突破 PPO ceiling 0.34 的下一步**:

1. **AZ + BC warm-start** (paradigm pivot 文档的 P0-1,核心 lever +0.24 in PPO)
   - infra: AZ-compatible BC dataset gen + BC training pipeline + ActorCritic load_from_bc
   - 估 2-3 day infra + 1-2 day 训练验证
2. **AZ + asymmetric self-play** (AZ vs F1-D{1,2} 固定对手,对照 PPO s012/s013 的 fixed-opponent 实验)
   - infra: rollout_opponent 字段在 AZ scenario,改 ~50 LOC
   - 估 0.5d infra + 1d 训练
3. **AZ + reward shaping** (重审 D5 决策,加 dense HP delta)
   - infra: AZ selfplay 接 env reward 累加 (env.step 已返 reward,只需 AZ 不忽略)
   - 估 0.5d infra + 1d 训练

**推荐 1**: BC warm-start 是 PPO 路线证实的 dominant lever (+0.24 in Stage 3),复用文献最强证据,与 paradigm pivot 文档原始 r009 plan 一致。

## 不推 Stage 4

不在 pure self-play 路径推 Stage 4 — Stage 4 加元素反应 / 多元素角色,vs F1-D2 plateau 会更弱。

## 详细数据

PPO closure 详细: [`../../5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md)

## 参考

- Plan: [`plan.md`](plan.md) Stage 3 章
- Memory: `project_stage3_full_diagnosis` (PPO), `project_az_stage3_baseline` (AZ s064-s066)
- AZ next step: [`../az_plans/r009_az_warmstart.md`](../az_plans/r009_az_warmstart.md) (BC warm-start AZ 路径)
- Paradigm pivot: [`../../2_decisions/adr-0008-rl_paradigm_pivot.md`](../../2_decisions/adr-0008-rl_paradigm_pivot.md)
