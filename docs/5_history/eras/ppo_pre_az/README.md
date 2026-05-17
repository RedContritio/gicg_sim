# PPO pre-AZ era 归档

> **⚠️ 重要澄清.** 本目录是 **r001 之前的老 PPO 时代** (phase{0-5}_{a,b,c,d} 课程体系)
> 的归档,2026-04-15 PPO→AZ 迁移落地 ([adr-0004 is_mcts_migration](../../../2_decisions/adr-0004-is_mcts_migration.md)) 时一并冻结。
>
> **不是** 当前 RL Curriculum era 的 PPO Stage 0-3 归档。后者是 paradigm pivot
> ([adr-0008](../../../2_decisions/adr-0008-rl_paradigm_pivot.md)) 后的新 PPO,
> 在 `training/ppo/` 仍 active。Stage 3 closure 沉淀见
> [`../../ablations/stage3_ppo_closure.md`](../../ablations/stage3_ppo_closure.md)。
>
> 区分:
> - **PPO pre-AZ era** (本目录): r001 之前,phase 体系,2026-04-15 冻结
> - **AZ era**: r001-r008 + C1 系列,2026-04-14 ~ 2026-04-23
> - **Curriculum era PPO**: 2026-04-24 paradigm pivot 后,Stage 0-3 BC warm-start

## 目录说明

- **decisions/** — PPO 时代的训练管线设计决策 (D14-D20)
- **network/** — PPO 网络架构、dropout 策略、shipped 代码结构说明
- **training/** — PPO 训练课程体系、超参、晋级逻辑、新卡奖励。更早一层的 `legacy/`
  (pretrain + rl_curriculum) 是 AZ 迁移之前就已经归档过一次的更古旧资料

## 使用须知

1. **不要基于这些文档写新代码**。当前训练决策走 [`../../../2_decisions/`](../../../2_decisions/)
2. 文档里的 link 多数指向**已废路径** (e.g. `docs/current/az/*`、`docs/decisions/*`)。
   2026-04-26 docs 大改后这些路径变了 (`docs/1_specs/`、`docs/2_decisions/`)。归档不批量修 link,
   断链被期望
3. **git 历史是权威**。想追溯某个 PPO 决策在当时的具体 shipped 状态,
   用 `git log --follow` + `git show <commit>`

## 归档日期

- 2026-04-15 — 配合 AZ step 1 (training/ PPO 清扫) 的文档部分补作 (原 `docs/archive/ppo_era/`)
- 2026-04-26 — docs 大改,`docs/archive/ppo_era/` mv 到当前位置 `docs/5_history/eras/ppo_pre_az/`
