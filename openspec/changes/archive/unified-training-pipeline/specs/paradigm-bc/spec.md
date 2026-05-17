---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: paradigm-bc
change_id: unified-training-pipeline
---

# Spec delta — paradigm-bc(new capability)

> 新 capability spec。BC(Behavior Cloning)算法层 SHALL invariants。架
> 构层继承 `training-architecture`,本 spec 只列 BC-specific 约束。
>
> D1 决策(本 change 内):BC **first-class** paradigm — 从 `training/az/bc_*.py`
> + `training/ppo/bc_*.py` 抽出独立 `paradigms/bc/`,不再 embedded。

## 1. Purpose

BC 是 GICG 当前 production fallback paradigm(r009 epoch_3 vs F1-D2 =
0.75,见 archive `0009-rl-paradigm-pivot-terminus`)。本 spec 治理 BC 算
法层不变量:

- 静态 dataset 训练(YAML / Parquet 离线)
- Cross-entropy(hard target)或 KL(soft target)loss
- (Policy,)单 head 网络,无 value head
- 不需要 env episode loop(SHALL NOT 调 env)

BC 也作为 RL paradigm 的 warm-start prior 被引用(AZ init_from_ckpt /
DMC pretrain),独立 first-class status 是必要的。

## 2. Scope

**In scope**:
- BC paradigm 实现的 6 protocol(Paradigm / Collector / Buffer /
  LossComputer / EpisodePolicy / NetworkProvider BC-specific 实现要求)
- Dataset loader(YAML expert replay → Transition stream)
- Hard target CE vs soft target KL 切换 cfg
- BC paradigm `requires_network_in_collect = False` 例外
- BC ckpt 作 RL warm-start 接口

**Out of scope**:
- 通用 EpisodeRunner / NetworkProvider → `training-architecture`
- BC dataset 生成 pipeline(replay → tfrecord/yaml)→ `tools/dataset/`
  (待 `tools-layout` spec)
- Teacher policy 选择(MCTS / dice_greedy)→ run-level decision,不属本 spec
- BC RL fine-tune(KL retention)→ future paradigm `paradigm-bc-ft`,本
  change 不引入

## 3. Core SHALL invariants

### BC1. 算法核心

1. **BC1.1** BC paradigm SHALL train on **static dataset**(YAML expert
   replay or Parquet),SHALL NOT 调 env episode loop。
2. **BC1.2** Dataset SHALL be loaded via `DatasetCollector`,one-shot push
   (no incremental rollout)。
3. **BC1.3** BC SHALL NOT depend on `NetworkProvider`(no network forward
   during collect)。

### BC2. Loss(CE / KL 切换)

4. **BC2.1** BC loss SHALL be cfg-driven:`paradigm.loss_kind = "ce"`
   (cross-entropy on hard expert action)或 `"kl"`(KL on teacher soft
   distribution),default `"ce"`。
5. **BC2.2** Hard target = expert action index;soft target = teacher
   policy logits(saved in dataset alongside)。
6. **BC2.3** No value loss,no entropy bonus(value head 不参与训练)。

### BC3. Buffer / Collector

7. **BC3.1** BC Collector SHALL be `DatasetCollector`,一次性把 dataset
   transitions push 到 buffer;`collect()` 是 no-op after first call。
8. **BC3.2** BC buffer SHALL be `DatasetBuffer`(全量 in-memory or memmap),
   capacity = dataset size。
9. **BC3.3** `requires_network_in_collect = False`(SHALL be honored by
   driver — skip provider construction during collect path)。

### BC4. Network heads

10. **BC4.1** BC network SHALL have 1 head:`policy_head(logits)`;value
    head SHALL NOT be trained(但 MAY 存在作为后续 RL warm-start init
    target,frozen during BC training)。
11. **BC4.2** Encoder SHALL be paradigm-agnostic(shared with AZ/DMC/PPO),
    所以 BC ckpt 可直接 load 进 RL paradigm(共享 encoder + 同维 policy head)。

### BC5. EpisodePolicy

12. **BC5.1** BC paradigm `EpisodePolicy` SHALL be `BCPolicy(argmax logits)`;
    eval 时复用,deterministic 默认 True。
13. **BC5.2** BC paradigm SHALL NOT 调 EpisodeRunner 在训练 path;仅 eval
    路径用(periodic eval 仍走 `training/core/eval/` 共享设施)。

### BC6. First-class tier

14. **BC6.1** BC tier SHALL be `first-class` paradigm,**SHALL NOT** be
    embedded in AZ / PPO / DMC paradigm(违反 D1 决策)。
15. **BC6.2** BC SHALL provide `export_for_warm_start(ckpt_path) ->
    state_dict` 接口,供其他 paradigm 通过 cfg `init_from_ckpt` 引用。
16. **BC6.3** BC = current production fallback;r009 epoch_3 ckpt SHALL
    remain accessible during paradigm migration(本 change ship 时验证
    ckpt load 成功)。

## 4. Cross-references

- 主 training architecture →
  [`../../../../specs/training-architecture/spec.md`](../../../../specs/training-architecture/spec.md)
- BC paradigm dossier → `docs/paradigms/bc/`
- BC warm-start history → memory `project_bc_warmstart_progress` +
  `project_bc_alone_evaluation`
- RL paradigm pivot terminus → `archive/0009-rl-paradigm-pivot-terminus`
- Phase 4 实施 →
  [`../../tasks/phase4-other-paradigms.md`](../../tasks/phase4-other-paradigms.md) §2

## 5. Status

- **Created**:2026-05-16(本 change ship 时新建 capability)
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied
- **Tier**:first-class — production fallback;接受 dataset 更新 + retrain
