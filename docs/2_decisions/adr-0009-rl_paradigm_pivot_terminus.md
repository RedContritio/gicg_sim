# ADR-0009: RL paradigm pivot terminus — self-play 不适用本游戏类

> **MOVED to `openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**Date:** 2026-04-28
**Status:** Accepted
**Supersedes:** [`adr-0008-rl_paradigm_pivot.md`](adr-0008-rl_paradigm_pivot.md) 的"BC warm-start 是 dominant lever"假设
**Decided by:** Empirical evidence,3 栈 × 5 stage 全失败

## Context

`adr-0008-rl_paradigm_pivot` 提出 PPO/AZ self-play 在大动作空间×隐藏信息×长 horizon 游戏类需要 hybrid 路径(BC warm-start + dense reward + greedy rollout leaf eval)。本 ADR 记录 BC warm-start 路径的最终实证 verdict,以及 self-play 范式在本游戏类的整体 closure。

## Empirical evidence

### 三栈 × 5 stage 数据矩阵(vs F1-D2 mean,Stage 3 stricter 阈值 ≥ 0.40)

| stage / spec | PPO | AZ pure self-play | AZ + BC warm-start |
|---|---|---|---|
| Stage 0(fix dice) | PASS(>0.40) | PASS(>0.40) | — |
| Stage 1(rand dice) | FAIL(0.07) | PASS(>0.40) | — |
| Stage 2(partial obs) | PASS | PASS | — |
| Stage 3 1-card(s064-066) | 0.344(BC→PPO best,FAIL stricter) | **0.104** | **0.167** |
| **Stage 3 3-card(s067)** | — | **0.0625** | — |

### BC alone vs F1-D2(对照基线)

| 模型 | vs F1-D2 |
|---|---|
| **r009 BC ckpt epoch_3(无 RL)** | **0.75** |
| AZ + BC warm-start 200g(r010 mean) | 0.167 |
| 200g AZ self-play 把 BC 0.75 → 0.167(**-0.58**) |  |

### 关键观察

1. **AZ self-play plateau 跨 stage 不变在 0.06-0.15**(memory `project_az_stage0_3_baselines` + s067 实证)
2. **复杂度增加让 RL 更弱**,不更强:s064-066 (1-card) F1-D2=0.104 → s067 (3-card) F1-D2=0.0625
3. **BC warm-start 在 AZ 中无效**:r010 vs s064-066 仅 +0.06,在 noise 边缘
4. **BC 单独已超 PPO ceiling**:0.75 >> 0.344,RL self-play 反向破坏 BC 的 hard-earned 优势
5. **PPO 路线同样:Stage 3 30+ ablation 没找到 +0.06 以上 lever**(memory `project_stage3_full_diagnosis`)

## Decision

### 1. 终止 self-play RL 范式探索(本游戏类)

不再尝试:
- AZ pure self-play
- AZ + BC warm-start
- PPO BC→PPO
- 增加 stage 复杂度(Stage 4/5)

证据足够强:**5 个 stage × 3 算法栈 = 15 个数据点,没有一个证伪"RL self-play 在这游戏类不 work"假设**。

### 2. Production model = r009 BC pretrain ckpt epoch_3

- vs F1-D2 = 0.75(实质达 stricter 0.40 by huge margin)
- vs random = 1.0
- vs mcts_pure_200 = 1.0
- BC 充分作为 production model

### 3. 保留作为可选未来研究方向(不在 closure 内)

`adr-0008` 提及但未尝试的子路径:
- **Dense reward + greedy rollout leaf eval** (MuZero-like 但 reward shaping 在 selfplay loop 内)
- **MuZero-style learned dynamics**(network 学环境模型,bypass 隐藏信息 / dice randomness)
- **Imitation learning extensions**(多 teacher mix / curriculum imitation / RL fine-tune with KL retention)

这些是 ≥ 1-2 周工作量,**不属于本 ADR closure 范围**;若产品需要更强 model 时再开 issue。

### 4. Curriculum 终止于 Stage 3(via BC)

- Stage 0/1/2:PPO/AZ 已验 PASS,但 RL 仅在易场景胜任;Stage 3 起 RL 无法超越 BC,因此**Stage 3 也算 closed by BC**
- **不开 Stage 4(多元素+反应)**:既然 Stage 3 1-card 已 closed by BC,Stage 4 加复杂度只会让 RL 更弱(s067 已证),BC 仍为最优解

## Consequences

### 正面

- **算力释放**:不再投入 RL self-play long runs(节省每 run 1-30h)
- **产品确定性**:BC ckpt 是确定性 production solution,可直接 ship
- **诚实记录**:负面结果作为 paradigm-pivot 文献预测的 **第二次实证**(第一次是 PPO Stage 1 撞墙;本 ADR 是 AZ 全栈撞墙)

### 负面

- **paradigm-pivot 文档主路径(BC warm-start)被否决** — 文档需 retroactively 标 OBSOLETE 或加注脚
- **MCTS 搜索价值未被 RL 利用** — 即 BC ckpt 不带搜索,纯 argmax;但 inference-time MCTS(BC-as-policy + handcrafted value)仍可在 production 加上,作为 BC 的搜索增强(不需要 train)

### 未尽问题

- F1-D2 真的接近最优吗?未做严格 optimal play vs F1-D2 比对(没有 ground truth)
- 网络架构(transformer + hook attention)是否过强 → BC 直接覆盖 F1-D2 + tied-noise reduction = 0.75。换小 MLP 会怎样?(无 ROI 探索)
- 跨 element / cross-team 泛化:r009 BC 只在 测试角色D mirror 训过;production 用前需在真角色 + 多 element 上验证 BC 是否泛化

## References

- `adr-0008-rl_paradigm_pivot.md` — 原假设
- `docs/5_history/runs_pre_redesign_2026_05_17.md` — s064-066, s067, r009, r010-012 数据
- `docs/5_history/r010_az_bc_warmstart_postmortem.md` — r010 失败诊断
- memory `project_az_stage0_3_baselines` — AZ pure plateau 数据
- memory `project_stage3_full_diagnosis` — PPO Stage 3 30+ ablation
- memory `project_rl_paradigm_pivot` — 文献预测,本 ADR 部分证实

## Verdict

**Self-play RL 在本游戏类(隐藏信息 + 大动作空间 + 短 horizon mirror match + 强 handcrafted baseline)结构性失败**。F1-D2 dice_greedy 是该类游戏的 near-ceiling baseline,RL 没有比 imitation-of-F1-D2 更好的策略可学。

Production = BC + 可选 inference-time MCTS;curriculum closed at Stage 3 via BC。
