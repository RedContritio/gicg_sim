---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-cfr
---

# Spec delta — paradigm-cfr

本 delta:import 路径切 + `cfr/legacy/` 扁平化 + 撤销 C6.2 r008 reproducibility 条款。详 `../../proposal.md`。

## ADD

### A1. 扁平化到主目录

`paradigms/cfr/` SHALL be 扁平结构:

```
paradigms/cfr/
├── __init__.py
├── config.py
├── network.py
├── paradigm.py
├── policy.py
├── loss.py
├── agent.py           ← 自 cfr/legacy/agent.py mv
├── strategy_net.py    ← 自 cfr/legacy/network/strategy_net.py mv(扁平化,删 network/ 子目录)
└── (其它 cfr/legacy/ 内容如 trainer 等同步 mv 上)
```

## MODIFY

### M1. Import paths

**Before**:
```python
# cfr/legacy/agent.py
from training.core.network.legacy.agent_base import AgentBase

# cfr/legacy/network/strategy_net.py
from training.core.network.legacy.trunk import (HookEncoder, CounterEncoder, CardEncoder, CrossAttentionBlock)
```

**After**:
```python
# cfr/agent.py
from training.core.network import AgentBase

# cfr/strategy_net.py
from training.core.network.encoder import (HookEncoder, CounterEncoder, CardEncoder, CrossAttentionBlock)
```

### M2. CFRAgent 构造改 DI

CFRAgent 用 `CFRStrategyNet`(自己的 nn.Module,不通过 generic `ActorCritic`)。`super().__init__(cfg, ...)` SHALL 改为 DI:`super().__init__(cfg, hook_encoder=self.net.hook_encoder, device=device)`。

注:CFR `CFRStrategyNet` 内部 own 一个 `HookEncoder` instance(来自 `core/network/encoder`,不是 ActorCritic 的 encoder),DI 注入这个 instance。

### M3. typed_damage 跳过

CFR `make_actor_critic` (若 P3-B 未来切到 generic) SHALL 用 `use_typed_damage=False` — CFR 当前 not consume typed segments(recent_damage / prepare_skill / modifier_log),与 design.md Tradeoffs 决策对齐。

## REMOVE

### R1. `cfr/legacy/` 子目录

`cfr/legacy/` 整目录 SHALL 不存在(扁平化到 `cfr/` 主目录)。

### R2. C6.2 r008 reproducibility 条款(SUPERSEDED)

`paradigm-cfr/spec.md` 若有 C6.2 或类似 "r008 ckpt reproducibility via cfr/legacy/" SHALL 加 SUPERSEDED 标。

理由:r008 ckpt schema 在本 change 后 obsolete(同 r009)。User 决策接受所有旧 ckpt 失效;若未来需要复现 r008 行为,通过 `git checkout pre-core-network-redesign-2026-05-17` + 老代码 + 老 cfg 走老路径,不在 main branch 维护并行栈。

### R3. legacy/trunk 引用

`paradigm-cfr/spec.md` 若引用 `core/network/legacy/trunk.py` 的 4 个 encoder class SHALL 改为 `core/network/encoder.py`(同名 class,内容严格更现代,per `proposal.md` 审计结果)。

## Cross-references

- `../../proposal.md` — change 整体
- `../network-architecture/spec.md` invariant A1/A2/A3 — generic primitives + DI + typed_damage optional
- `../../design.md` Migrations 节 — r008 reproducibility 失效说明
- `../../tasks.md` Phase 2D — CFR 切实施
