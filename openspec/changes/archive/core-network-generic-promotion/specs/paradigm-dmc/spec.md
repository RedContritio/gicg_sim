---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-dmc
---

# Spec delta — paradigm-dmc

本 delta:5 处 import 路径切到新 generic root + DmcAgent 构造改 DI。详 `../../proposal.md`。

## MODIFY

### M1. Import paths(5 处)

`paradigms/dmc/{_agent,network,paradigm,_run_config}.py` 全部 import:

**Before**:
```python
from training.core.network.legacy.agent_base import AgentBase, AgentConfig
from training.core.network.legacy.actor_critic import ActorCritic
```

**After**:
```python
from training.core.network import AgentBase, AgentConfig, ActorCritic, make_actor_critic
```

### M2. DmcAgent 构造改 DI

**Before**:
```python
class DmcAgent(AgentBase):
    def __init__(self, cfg, device='cpu', lr=1e-4, weight_decay=0.0, epsilon=0.0):
        super().__init__(cfg, device=device)
        self.net = ActorCritic(n_counter_slots=cfg.n_counter_slots, ...)
```

**After**:
```python
class DmcAgent(AgentBase):
    def __init__(self, cfg, device='cpu', lr=1e-4, weight_decay=0.0, epsilon=0.0):
        # DMC uses logits as Q values (decision A1: logit-as-Q)
        self.net = make_actor_critic(cfg, head_kinds={'q'}, use_typed_damage=True)
        super().__init__(cfg, hook_encoder=self.net.encoders['hook'], device=device)
```

注:DMC 之前 ActorCritic 同时有 policy+value+delta head 但只用 logits 当 Q;现在改用 `head_kinds={'q'}` 单 head,数学等价 + 网络更轻量。

### M3. DMCNetwork wrapper 内部更新

`DMCNetwork` 内 `self._agent = DmcAgent(agent_cfg, ...)` 不变;只是底层 `DmcAgent.net` 从 god ActorCritic 换成 generic ActorCritic 单 Q head。`DMCNetwork.add_module('net', self._agent.net)` 仍生效。

## REMOVE

### R1. legacy/ 引用

`paradigm-dmc/spec.md` 若引用 `core/network/legacy/` SHALL 全部删除。

## Cross-references

- `../../proposal.md` — change 整体
- `../network-architecture/spec.md` invariant A1/A2 — generic ActorCritic + AgentBase DI(DMC 是用户)
- `../config-schema/spec.md` invariant A1 — ObsShape 共享(DMC cfg compose)
- DMC `decision A1` (logit-as-Q) — 不变,通过 single QHead 实现
