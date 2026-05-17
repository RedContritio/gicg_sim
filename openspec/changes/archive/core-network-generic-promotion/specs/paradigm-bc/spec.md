---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-bc
---

# Spec delta — paradigm-bc

本 delta:import 路径切 + `bc/legacy/` 扁平化到主目录 + 清理 BC PPO variant 残留引用。详 `../../proposal.md`。

## ADD

### A1. 扁平化到主目录

`paradigms/bc/` SHALL be 扁平结构(与 AZ / DMC 已扁平 paradigm 形态对齐):

```
paradigms/bc/
├── __init__.py
├── config.py          (paradigm cfg)
├── network.py         (BCNetwork wrapper)
├── paradigm.py        (BCParadigm entry)
├── policy.py
├── loss.py            (BCLoss class)
├── train.py           ← 自 bc/legacy/bc_train.py mv
├── dataset.py         ← 自 bc/legacy/bc_dataset.py mv
└── README.md          (含 bc/legacy/README.md 内容)
```

`bc/legacy/bc_loss.py`(legacy 训练 CLI 内部 loss 函数)SHALL inline 到 `bc/train.py`(唯一 caller),SHALL NOT 与 `bc/loss.py`(paradigm BCLoss class)合并。

## MODIFY

### M1. Import paths

**Before**:
```python
# bc/network.py + bc/legacy/bc_train.py + bc/legacy/bc_loss.py
from training.core.network.legacy.actor_critic import ActorCritic
```

**After**:
```python
from training.core.network import ActorCritic, make_actor_critic
```

### M2. BCNetwork 构造改 DI

`BCNetwork` 内 `ActorCritic(...)` 直接构造 SHALL 改为 `make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'}, use_typed_damage=True)`(value/delta head 保留以支持 AZ/PPO/DMC `init_from_ckpt` 共享 encoder,per BC4.2 spec)。

## REMOVE

### R1. `bc/legacy/` 子目录

`bc/legacy/` 整目录 SHALL 不存在(扁平化到 `bc/` 主目录,per A1)。

### R2. BC PPO variant 残留引用

`paradigm-bc/spec.md` 若残留 BC PPO variant(`bc_train_ppo.py` / `bc_losses_ppo.py` / `_ppo_net.py`)引用 SHALL 全部删除 — 这些已在 W4-PPO retire 一并删除(commit `2e5bc6f`)+ W1A followup `1cb1bec` / `2d0584b`。

### R3. r009 BC pretrain ckpt 引用(SUPERSEDED)

`paradigm-bc/spec.md` 若引用 "r009 BC pretrain ckpt as production fallback" SHALL 加 SUPERSEDED 标。理由同 paradigm-az spec delta R1。

## Cross-references

- `../../proposal.md` — change 整体
- `../network-architecture/spec.md` invariant A1/A2 — generic backbone + DI
- `../paradigm-az/spec.md` R1 — r009 ckpt 撤销同步
- ADR-0009 — SUPERSEDED
