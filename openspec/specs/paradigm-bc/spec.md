---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: paradigm-bc
---

# Paradigm BC — Behavior Cloning 算法层不变量

> BC(Behavior Cloning)paradigm 的算法层 SHALL invariants。架构层继承
> [`../training-architecture/spec.md`](../training-architecture/spec.md),
> 本 spec 只列 BC-specific 约束。
>
> D1 决策(unified-training-pipeline 内):BC **first-class** paradigm —
> 从 `training/az/bc_*.py` + `training/ppo/bc_*.py` 抽出独立
> `paradigms/bc/`,不再 embedded。

## 1. Purpose

BC 是 GICG 当前 production fallback paradigm(r009 epoch_3 vs F1-D2 =
0.75,见 archive `0009-rl-paradigm-pivot-terminus`;ckpt 本身在
`core-network-generic-promotion` archive 2026-05-17 撤销 — 详 BC6.3,
paradigm 第一类 status 保留)。本 spec 治理 BC 算法层不变量:

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
11. **BC4.2** Encoder SHALL be paradigm-agnostic(shared with AZ/DMC/PPO
    via `core/network/ActorCritic` backbone),所以 BC ckpt 可直接 load 进
    RL paradigm(共享 encoder + 同维 policy head)。`BCNetwork` SHALL 通过
    `make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'},
    use_typed_damage=True)` 装配(value/delta head 保留以支持
    AZ/PPO/DMC `init_from_ckpt` 共享 encoder),`AgentBase` 通过 DI 注入
    `hook_encoder=self.net.encoders['hook']`(详 `network-architecture/
    spec.md` invariants 12-13)。Imports SHALL use generic root:
    `from training.core.network import ActorCritic, make_actor_critic`。

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
16. **BC6.3** BC = current production fallback paradigm。**r009 epoch_3
    ckpt 撤销(SUPERSEDED)**:
    > ~~r009 BC pretrain ckpt as production fallback~~ — SUPERSEDED by
    > `core-network-generic-promotion` (archive 2026-05-17)。理由同
    > `paradigm-az` A6.2:r009 ckpt 自 2026-05-08 ADR-0019 typed obs ckpt
    > break 后 strict-load 名存实亡,User 决策正式撤销:接受全部 ckpt
    > 失效,需要 production fallback 时重 train BC ckpt on new schema
    > (paradigm 自身 first-class status 保留)。ADR-0009 同步
    > SUPERSEDED-BY:`core-network-generic-promotion`。

### BC7. Filesystem layout(扁平化)

> Added by `core-network-generic-promotion` (archived 2026-05-17) —
> `paradigms/bc/legacy/` 整目录退役,与 AZ / DMC 已扁平 paradigm 形态对
> 齐。

17. **BC7.1** `paradigms/bc/` SHALL be 扁平结构(与 AZ / DMC 已扁平
    paradigm 形态对齐):

    ```
    paradigms/bc/
    ├── __init__.py
    ├── config.py          (paradigm cfg)
    ├── network.py         (BCNetwork wrapper,via make_actor_critic + DI)
    ├── paradigm.py        (BCParadigm entry)
    ├── policy.py
    ├── loss.py            (BCLoss class)
    ├── train.py           ← 自 bc/legacy/bc_train.py mv(扁平化)
    ├── dataset.py         ← 自 bc/legacy/bc_dataset.py mv(扁平化)
    └── README.md          (含 bc/legacy/README.md 内容)
    ```

    `bc/legacy/bc_loss.py`(legacy 训练 CLI 内部 loss 函数)SHALL inline
    到 `bc/train.py`(唯一 caller),SHALL NOT 与 `bc/loss.py`(paradigm
    BCLoss class)合并。

18. **BC7.2** `bc/legacy/` 整目录 SHALL 不存在(扁平化到 `bc/` 主目录,
    per BC7.1)。

19. **BC7.3** BC PPO variant(`bc_train_ppo.py` / `bc_losses_ppo.py` /
    `_ppo_net.py`)SHALL NOT exist — 已在 W4-PPO retire commit `2e5bc6f`
    + W1A followup `1cb1bec` / `2d0584b` 一并删除。新 BC code SHALL NOT
    引用这些路径。

## 4. Cross-references

- 主 training architecture →
  [`../training-architecture/spec.md`](../training-architecture/spec.md)
- BC paradigm dossier → `docs/paradigms/bc/`
- BC warm-start history → memory `project_bc_warmstart_progress` +
  `project_bc_alone_evaluation`
- RL paradigm pivot terminus → `archive/0009-rl-paradigm-pivot-terminus`
- Originating change(archived)→
  [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)

## 5. Status

- **Created**:2026-05-16(unified-training-pipeline P6 archive)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)—
  MODIFY BC4.2(generic ActorCritic via `make_actor_critic` + AgentBase DI);
  +BC6.3 r009 BC pretrain ckpt SUPERSEDED(ADR-0009 同步);+BC7 扁平化
  layout(`bc/legacy/` 退役 + BC PPO variant 一并删除)。
- **Version**:0(初始)
- **Implementation**:Phase 4 落地;P4 ship 时 SHALL satisfied;
  `core-network-generic-promotion` Phase 2C(2026-05-17)BC 扁平化 +
  generic backbone 接入完成
- **Tier**:first-class — production fallback;接受 dataset 更新 + retrain
