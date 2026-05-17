---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
capability: config-schema
---

# Spec delta — config-schema

> 本 delta 调整 PPOAgentShapeCfg 字段集与其它 paradigm AgentShapeCfg
> 对齐(N1-prep)。不完成完整 ObsShape unification(D-201 仍 defer 到
> `cfg-schema-unification` follow-up change)。

## ADD

### CS-PPO-1. PPOAgentShapeCfg 字段集对齐

> **CS-PPO-1**:`paradigms/ppo/config.py::PPOAgentShapeCfg` 字段集 SHALL
> 与 BC/AZ/DMC `AgentShapeCfg` 字段集一致,即:
>   - `n_counter_slots: int`
>   - `n_hooks: int`
>   - `max_tokens_per_hook: int`
>   - `max_actions: int`
>   - `d_model: int`
>   - `n_cross_layers: int`
>   - `dropout: float`
>
> 字段集对齐为后续 `cfg-schema-unification`(D-201)follow-up change
> 的 ObsShape replace 铺路 — 替换时无需 paradigm-specific field migration
> 逻辑。

## REMOVE

### R-PPO-CS-1. flat MLP 专用字段删除

> **R-PPO-CS-1**:`PPOAgentShapeCfg.n_hidden_layers: int` SHALL 删除。

理由:`n_hidden_layers` 是 flat MLP `_PPOMLPTrunk` 专用参数(控制
trunk MLP 层数);structural backbone via `make_actor_critic` 用
`n_cross_layers` 控制 CrossAttention 层数,语义 entirely 不同。物理删
除 + 同名 fallback 都不接受(per CLAUDE.md "不接受变通方案" + memory
`feedback_no_compat_fallback`)。

## Cross-references

- `../../proposal.md` — 本 change scope
- `../paradigm-ppo/spec.md` — R4 字段层 cross-reference
- `core-network-generic-promotion/DECISIONS.md` [D-201] — ObsShape
  unification follow-up change(本 change 完成字段对齐,不替换类型)
