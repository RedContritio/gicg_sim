---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# BC postmortems

> BC paradigm 的失败模式都已在 5_history 复盘,本 dossier 只列入口 +
> paradigm-level 总结。

## 主要 postmortem 来源

| Topic | Canonical doc |
|---|---|
| r010 BC + AZ destruction | [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md) |
| Stage 3 BC + PPO 4-factor ceiling | [`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md) |
| r009 BC pretrain plan(已归档)| [`docs/5_history/az_plans/r009_az_warmstart.md`](../../5_history/az_plans/r009_az_warmstart.md) |
| BC alone production OK / RL 研究意义 | memory `project_bc_alone_evaluation` |

## Paradigm-level 失败 / 局限 root cause(总结)

### 1. F1-D2 teacher tiebreak noise(hard ceiling 0.354)

BC data 50k decisions / tied_mask mean 2.83 → F1-D2 random tiebreak over ~3 ties
per decision → BC **hard-match physical ceiling 0.354**(无法 perfectly imitate
random tiebreak)。Soft target distillation 突破之(s016d 73% / s019 66% /
s022 62%),但 distillation noise floor 仍在,且 paradigm 上限受 teacher 自身策略
质量约束。

### 2. BC + AZ destruction(r010)

PPO 路线 BC warm-start +0.24 dominant lever,AZ 路线只 +0.063(0.104 → 0.167)。
完整诊断 → [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)。
三层 root cause(memory `project_bc_warmstart_progress`):

1. **Random-init value head** + shared trunk → 早期 noise 通过 trunk 流回 policy,
   摧毁 BC prior。
2. **Determinize**:opp turn 用 sampled belief,policy 看到的 distribution 与 BC
   data(F1-D2 teacher full-info)不一致,distribution shift fast。
3. **Self-play noise reward**:无 BC anchor 同时 self-play 标 reward 噪声大。

PPO 路线为何不 destroy:PPO loss 直接对 BC distribution 的 KL 反 regularize,且
no value-head random init 问题(separate optimizer step)。

### 3. Stage 3 multi-card 0.10 plateau(paradigm-independent)

BC + PPO multi-card Stage 3 = 0.073-0.104(s023-25 / s043/46/47);AZ multi-card =
0.062 ± 0.062(s067)。BC 不能 magic 跨过 card combinatorial breadth — paradigm
共享 GICG 架构层 cliff,详 [`../ppo/postmortems.md`](../ppo/postmortems.md) §5。

### 4. Zero-shot 跨角色 / 卡池 NOT 学得到(memory `project_bc_alone_evaluation`)

GICG ActorCritic 架构 + ID-blind 决策 → BC 在 fixed 角色/卡池上学到的 policy
不能 generalize 到 v_phase2 真实 deck 或新角色。**Production maintenance**(同 stage
同 pool)OK,**RL 研究意义有限**:F1-D2 ceiling at Stage 3,无 paradigm-level 路径
突破 zero-shot generalization gap。

## Production fallback 决策路径

- **2026-04-25**:s017 BC + PPO Stage 1 F1-D2 = 0.500 PASS → BC warm-start 进入 production
  pipeline
- **2026-04-26**:Stage 3 BC + PPO ceiling 0.344 confirmed → 转 AZ paradigm
- **2026-04-28**:r009 BC pretrain Stage 3,epoch_3 vs F1-D2 = 0.75 — **BC ckpt 单独
  比任何 RL fine-tune 都强**
- **2026-04-28**:r010 BC + AZ FAIL → ADR-0009 钦定 BC ckpt(epoch_3)作 production fallback
- **2026-05-12**:user 评估 closure 集合,BC alone production OK / 不再做 BC-as-RL-base 研究

## 不 actionable 的 follow-up(知识保留)

- **更强 teacher(F1-D2 dice_greedy=true / F1-D3)**:s044/45 已试 F1-D3 teacher
  Stage 3 +0.10,combo 非 additive
- **Multi-seed BC**(s022 共享 BC seed=0):BC-seed variance 未量化;若 PPO/AZ
  reopen,SHOULD 做 BC-seed × PPO-seed 2D matrix
- **Joint BC + value head pretrain**:r010 postmortem 假设 value head random init
  是 AZ destruction 主因,可试 frozen value head 0.5 epoch 后 unfreeze
- **Distillation from MCTS-rollout policy**(non-greedy teacher):s007 显示 mcts_200
  vs F1-D2 = 0.10 — mcts 弱于 F1-D2,无 dataset 价值;但 mcts_pure_400+ 未测,
  可能作 teacher

## 不再追的方向(明确 closure)

- **Hard target BC**(s015 baseline 假设):被 tied_mask mean 2.83 物理 ceiling
  0.354 卡死,soft target 已是 paradigm 最优。
- **BC alone for Stage 4/5 curriculum**:zero-shot 跨角色/卡池不学得到,curriculum
  路线 ADR-0009 closed。
