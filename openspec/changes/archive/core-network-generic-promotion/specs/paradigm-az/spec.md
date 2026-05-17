---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-az
---

# Spec delta — paradigm-az

本 delta 撤销 r009 production fallback 条款 + import 路径切到新 generic root。详 `../../proposal.md`。

## MODIFY

### M1. Import paths

`paradigms/az/network.py` import 路径:

**Before**:
```python
from training.core.network.legacy.actor_critic import ActorCritic
from training.core.network.legacy.agent_base import AgentBase, AgentConfig
```

**After**:
```python
from training.core.network import ActorCritic, AgentBase, AgentConfig, make_actor_critic
```

### M2. Agent class 构造改 DI

**Before**:
```python
class Agent(AgentBase):
    def __init__(self, cfg, device='cpu'):
        super().__init__(cfg, device=device)
        self.net = ActorCritic(n_counter_slots=cfg.n_counter_slots, ...)
        # AgentBase hidden contract: self.net.hook_encoder must exist
```

**After**:
```python
class Agent(AgentBase):
    def __init__(self, cfg, device='cpu'):
        self.net = make_actor_critic(cfg, head_kinds={'policy', 'value', 'delta'}, use_typed_damage=True)
        super().__init__(cfg, hook_encoder=self.net.encoders['hook'], device=device)
```

## REMOVE

### R1. r009 production fallback 条款(SUPERSEDED)

主 `paradigm-az/spec.md` 若引用 "r009 ckpt as production fallback per ADR-0009"(或类似表述)SHALL 全部删除或加 SUPERSEDED 标。

理由(per `../../proposal.md`):
- r009 ckpt 自 2026-05-08 ADR-0019 后 strict-load 名存实亡,non-strict load 也仅 best-effort
- User 决策正式撤销:接受全部 ckpt 失效,需要 production fallback 时重 train r009-equivalent on new schema
- ADR-0009 同步标 SUPERSEDED-BY: core-network-generic-promotion

### R2. legacy/ 引用

`paradigm-az/spec.md` 若引用 `paradigms/az/legacy/` 子目录(如 `legacy/network/agent.py`)SHALL 全部删除 — AZ legacy 已在 archive `az-paradigm-rewrite` change 完成物理删除(commit `d305a10`)。

## Cross-references

- `../../proposal.md` — r009 production fallback 撤销动机
- ADR-0009 — RL paradigm pivot(同步 SUPERSEDED)
- `../network-architecture/spec.md` invariant A1/A2 — generic ActorCritic + AgentBase DI(AZ 是 first user)
- `../config-schema/spec.md` invariant A1/A2 — ObsShape + ParadigmConfigBase(AZ cfg compose)
- archive `az-paradigm-rewrite` — 前置完成 AZ legacy retire
