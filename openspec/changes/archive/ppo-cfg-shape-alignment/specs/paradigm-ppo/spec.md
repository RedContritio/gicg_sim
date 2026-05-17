---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: paradigm-ppo
---

# Spec delta — paradigm-ppo

post `ppo-structural-backbone-migration` (#4) + `cfg-schema-unification` (#3) 后剩余 partial:PPO cfg dataclass 仍 paradigm-local `PPOAgentShapeCfg`,与 4/5 paradigm `AgentShapeCfg = ObsShape` 不对称(per `cfg-schema-unification` CC-206 deferred + `ppo-structural-backbone-migration` D-101 closure note)。本 delta 闭 5/5 paradigm cfg dataclass 完全对称。

## MODIFY

### M-CS-PPO-1: PPOAgentShapeCfg 改为 ObsShape 别名

**Before**:
```python
@dataclass(frozen=True)
class PPOAgentShapeCfg:
    n_counter_slots: int = 2 * 6 * 128 + 2 * 140 + 16
    n_hooks: int = 900
    max_tokens_per_hook: int = 120
    max_actions: int = 2048
    d_model: int = 128
    n_cross_layers: int = 2
    dropout: float = 0.0
```

**After**:
```python
from training.core.cfg import ObsShape, make_ppo_default_shape

PPOAgentShapeCfg = ObsShape  # backward-compat alias (CC-202 pattern)

@dataclass(frozen=True)
class PPOParadigmConfig(ParadigmConfigBase):
    paradigm: str = 'ppo'
    agent: ObsShape = field(default_factory=make_ppo_default_shape)
```

### M-CS-PPO-2: PPOParadigmConfig inherit ParadigmConfigBase

**Before**:
```python
@dataclass(frozen=True)
class PPOParadigmConfig:
    # 无 version + paradigm 字段
    ...
```

**After**:
```python
@dataclass(frozen=True)
class PPOParadigmConfig(ParadigmConfigBase):
    paradigm: str = 'ppo'  # PB.PRG (paradigm dispatch contract)
    # version inherited from ParadigmConfigBase = '1.0.0'
    ...
```

### M-CS-PPO-3: from_dict 加 version + paradigm 校验

PPO `from_dict` 加 CC-204(version 枚举 frozenset)+ CC-205(paradigm 字段值校验)+ `build_shape_from_toml` 调用(CC-303 dict merge pattern)。

## ADD

### A-CS-PPO-4: make_ppo_default_shape factory

`training/core/cfg/factories.py` 加 `make_ppo_default_shape() -> ObsShape`,返回 d_model=128 / n_cross_layers=2(post-#4 structural defaults,与 AZ 同 baseline;flat-MLP 历史 d_model=256 retired in #4)。Export 入 `training.core.cfg.__init__`。

## Cross-references

- `cfg-schema-unification` CC-206(PPO 不接 deferred)→ **closed** by this change
- `ppo-structural-backbone-migration` D-101(backbone migration)→ pre-requisite
- `core-network-generic-promotion` DECISIONS D3 endpoint推荐 → fulfilled
- `paradigm-ppo/spec.md` CS-PPO-1(post #4 字段对齐)→ closure note

## Status

- Created: 2026-05-17
- Implementation commit: see git log
- Tests: pytest pass (160 cfg+ppo + 12 config_loader + 1159 full sweep,0 failures)
