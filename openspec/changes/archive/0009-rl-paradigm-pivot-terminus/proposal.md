# RL paradigm pivot terminus — self-play 不适用本游戏类

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0009-rl_paradigm_pivot_terminus.md` at P1-T1)
**Original date:** 2026-04-28
**Original status:** Accepted
**Supersedes:** [`../0008-rl-paradigm-pivot/`](../0008-rl-paradigm-pivot/) 的 "BC warm-start 是 dominant
lever" 假设
**Superseded by:** Partially superseded by [`../0010-rl-research-reopen/`](../0010-rl-research-reopen/)
— 同日下午 s068 D4 asymmetric +0.167 数据点部分推翻 closure decision(production fallback r009 BC ckpt
仍生效,closure 命题部分推翻仅限 "RL self-play 完全不可救" 强命题)。

## Why

`adr-0008-rl_paradigm_pivot` 提出 PPO/AZ self-play 在大动作空间×隐藏信息×长 horizon 游戏类需要 hybrid
路径(BC warm-start + dense reward + greedy rollout leaf eval)。本 ADR 记录 BC warm-start 路径的最终
实证 verdict,以及 self-play 范式在本游戏类的整体 closure。

### 三栈 × 5 stage 数据矩阵(vs F1-D2 mean,Stage 3 stricter 阈值 ≥ 0.40)

| stage / spec | PPO | AZ pure self-play | AZ + BC warm-start |
|---|---|---|---|
| Stage 0 (fix dice) | PASS (>0.40) | PASS (>0.40) | — |
| Stage 1 (rand dice) | FAIL (0.07) | PASS (>0.40) | — |
| Stage 2 (partial obs) | PASS | PASS | — |
| Stage 3 1-card (s064-066) | 0.344 (BC→PPO best, FAIL stricter) | **0.104** | **0.167** |
| **Stage 3 3-card (s067)** | — | **0.0625** | — |

### BC alone vs F1-D2(对照基线)

| 模型 | vs F1-D2 |
|---|---|
| **r009 BC ckpt epoch_3(无 RL)** | **0.75** |
| AZ + BC warm-start 200g (r010 mean) | 0.167 |
| 200g AZ self-play 把 BC 0.75 → 0.167 (**-0.58**) | |

### 关键观察

1. AZ self-play plateau 跨 stage 不变在 0.06-0.15
2. 复杂度增加让 RL 更弱不更强:s064-066 1-card F1-D2=0.104 → s067 3-card F1-D2=0.0625
3. BC warm-start 在 AZ 中无效:r010 vs s064-066 仅 +0.06,在 noise 边缘
4. BC 单独已超 PPO ceiling:0.75 >> 0.344,RL self-play 反向破坏 BC hard-earned 优势
5. PPO 路线同样:Stage 3 30+ ablation 没找到 +0.06 以上 lever

## What

1. **终止 self-play RL 范式探索(本游戏类)** — 不再尝试 AZ pure self-play / AZ + BC warm-start /
   PPO BC→PPO / 增加 stage 复杂度(Stage 4/5)。证据足够强:5 stage × 3 算法栈 = 15 数据点,没有一个
   证伪 "RL self-play 在这游戏类不 work" 假设
2. **Production model = r009 BC pretrain ckpt epoch_3** — vs F1-D2 = 0.75 / vs random = 1.0 /
   vs mcts_pure_200 = 1.0;BC 充分作为 production model
3. **保留作为可选未来研究方向(不在 closure 内)**:
   - Dense reward + greedy rollout leaf eval(MuZero-like 但 reward shaping 在 selfplay loop 内)
   - MuZero-style learned dynamics(network 学环境模型 bypass 隐藏信息 / dice randomness)
   - Imitation learning extensions(多 teacher mix / curriculum imitation / RL fine-tune with KL retention)
   这些 ≥ 1-2 周工作量,**不属于本 ADR closure 范围**;若产品需要更强 model 时再开 issue
4. **Curriculum 终止于 Stage 3 (via BC)** — Stage 0/1/2 PPO/AZ 已验 PASS,但 RL 仅在易场景胜任;
   Stage 3 起 RL 无法超越 BC,因此 **Stage 3 也算 closed by BC**。**不开 Stage 4(多元素+反应)**:
   Stage 3 1-card 已 closed by BC,Stage 4 加复杂度只会让 RL 更弱(s067 已证),BC 仍最优

## Affected specs

- `paradigm-az` (终止 self-play 探索)
- `paradigm-bc` (production 决策)
- `paradigm-ppo` (终止 self-play 探索)
- `paradigm-curriculum` (Stage 3 closure)
