---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: config-schema
subtopic: obs-shape-unification
---

# Config Schema — ObsShape + cfg version + configs/ layout

> 本 subtopic 落地 `config-schema` § 3 CS5(N1.1-N5.5)三件套:`ObsShape`(observation
> shape SoT,5 paradigm 共用)、`ParadigmConfigBase`(metadata fields:
> version + paradigm)、cfg version 字段 + enum validation。配套
> `configs/<paradigm>/{default,smoke}.toml` 提供 5 paradigm 标准 cfg
> layout。
>
> 适用范围:5 paradigm(AZ / BC / CFR / DMC / PPO)。PPO 自
> `ppo-structural-backbone-migration` archive 2026-05-17 起 `PPOAgentShapeCfg`
> 字段集与 ObsShape 对齐(`n_counter_slots / n_hooks / max_tokens_per_hook
> / max_actions / d_model / n_cross_layers / dropout` — flat MLP 专用字段
> `n_hidden_layers` 删除),PPO 走 structural backbone 后与其它 4 paradigm
> 完全对称。

## N1. ObsShape 单一 source of truth

**N1.1** `training/core/cfg/shape.py::ObsShape` SHALL be the single dataclass
representing observation shape parameters used by network construction across
5 paradigm(AZ / BC / CFR / DMC / PPO)。

**N1.2** Each of 5 paradigm `<X>ParadigmConfig` SHALL compose `ObsShape` via
`agent: ObsShape = field(default_factory=make_<x>_default_shape)` —
factory function from `training/core/cfg/factories.py` 提供 paradigm 历史
production defaults。

**N1.3** Paradigm-local type aliases `AgentShapeCfg = ObsShape`
(in AZ / BC / DMC config.py) + `CFRAgentShapeCfg = ObsShape`
(in CFR config.py) SHALL be preserved for backward compatibility with
existing import sites(`bc/network.py:21` 等;test_<paradigm>_paradigm.py
isinstance check 等)。

**N1.4** PPO 自 `ppo-structural-backbone-migration` archive 2026-05-17 起
接入字段对齐:`PPOAgentShapeCfg` 字段集 SHALL 与 `ObsShape` 完全一致
(`n_counter_slots / n_hooks / max_tokens_per_hook / max_actions / d_model
/ n_cross_layers / dropout`),flat MLP 专用 `n_hidden_layers` 字段 SHALL
不存在(per `paradigm-ppo/spec.md` invariant P7.8)。原 CC-206 PPO defer
决策 RESOLVED。`PPOAgentShapeCfg = ObsShape` type alias 形式仍可由 follow-up
完成(per `cfg-schema-unification` DECISIONS [CC-206 → 后续 SHALL] 衍生
follow-up;本 invariant 适用范围 = 5 paradigm 的字段对齐部分)。

## N2. ParadigmConfigBase compose

**N2.1** `training/core/cfg/base.py::ParadigmConfigBase` SHALL provide
two paradigm-agnostic metadata fields:
- `version: str = '1.0.0'` — cfg schema version
- `paradigm: str = ''` — paradigm dispatch key, subclass override

**N2.2** Each of 5 paradigm `<X>ParadigmConfig` SHALL inherit `ParadigmConfigBase`
via `@dataclass(frozen=True) class <X>ParadigmConfig(ParadigmConfigBase): ...`,
override `paradigm: str = '<x>'`(per dispatch key)。

**N2.3** `ParadigmConfigBase` SHALL NOT contain a `shape` field
(per `cfg-schema-unification` DECISIONS [CC-203]):subclass 通过 `agent: ObsShape`
field 提供 shape,base 加 `shape` 字段会成 dead field。

## N3. cfg version 字段 + enum validation

**N3.1** Each paradigm cfg `from_dict({...})` SHALL accept optional `version`
key;若缺省默认 `'1.0.0'`(dataclass default)。

**N3.2** Each paradigm `from_dict` SHALL validate `version` ∈ closed enum
`{'1.0.0'}`(future bump 通过新 OpenSpec change);unknown version → raise
`'paradigm cfg unsupported version: <X>'`。

**N3.3** Each paradigm `from_dict` SHALL validate `paradigm` key(若 toml 显式提供)
matches own dispatch key;mismatch → raise
`'paradigm mismatch: expected <self>, got <toml_value>'`。

**N3.4** `from_dict({})`(空 dict)SHALL succeed using all defaults
(version = `'1.0.0'`, paradigm = `'<x>'`, agent = factory result, sub-cfg = factory result)。

## N4. (skip — held by parent CS5.4 ckpt schema in `../spec.md` § 3)

## N5. configs/<paradigm>/{default,smoke}.toml(5/5 complete)

**N5.1** `configs/` SHALL contain per-paradigm subdirectory for 5 paradigm
(AZ / BC / CFR / DMC / PPO):
- `configs/az/{default,smoke}.toml`
- `configs/bc/{default,smoke}.toml`
- `configs/cfr/{default,smoke}.toml`
- `configs/dmc/{default,smoke}.toml`
- `configs/ppo/{default,smoke}.toml`

**N5.2** Each `default.toml` SHALL declare paradigm-specific production
defaults(参考 `_archived/{shipped,active}/`)。

**N5.3** Each `smoke.toml` SHALL declare minimum viable cfg(d_model=32 /
n_iter=1 / total_games small / max_steps=30)足够 smoke pipeline alive
verify。

**N5.4** Each toml `[paradigm]` section SHALL contain `version` + `paradigm`
keys explicitly matching cfg dispatch(N3.3 验证)。

**N5.5** PPO `configs/ppo/{default,smoke}.toml` 自
`ppo-structural-backbone-migration` archive 2026-05-17 起 SHALL be present,
fields aligned to structural backbone `[paradigm.ppo.agent]` 段
(`n_counter_slots / n_hooks / max_tokens_per_hook / max_actions / d_model
/ n_cross_layers / dropout` — per N5.2 / N5.3 共同适用规约)。原 PPO
N5 partial compliance 状态 RESOLVED。

## Cross-references

- Originating change → `openspec/changes/archive/cfg-schema-unification/proposal.md`
- DECISIONS log → `openspec/changes/archive/cfg-schema-unification/DECISIONS.md`
  - CC-201: agent field name(not shape)
  - CC-202: AgentShapeCfg type alias preserved
  - CC-203: ParadigmConfigBase drop shape field
  - CC-204: version `'1.0.0'` enum
  - CC-205: paradigm field mismatch raise
  - CC-206: PPO defer per D-202 paired follow-up
  - CC-207: configs toml content selection
  - CC-208: n_counter_slots=1832 in smoke(not 66)
- Predecessor change(deferred decisions)→
  `openspec/changes/archive/core-network-generic-promotion/DECISIONS.md` D-201 / D-202 / D-204
- Parent SHALL summary in main spec.md → § 3 CS5.1-CS5.5
- N4(ckpt self-describing schema)merged by parent change as CS5.4(本 subtopic 跳过)
