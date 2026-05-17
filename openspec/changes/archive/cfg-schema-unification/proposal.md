---
last_updated: 2026-05-17
status: DRAFT
schema_version: 0
change_id: cfg-schema-unification
---

# Proposal — cfg-schema-unification

## 1. Why

post `core-network-generic-promotion` 留下 3 个 paired deferred
decisions(per DECISIONS.md D-201/202/204)。当前 4 paradigm(AZ/BC/CFR/DMC)
config.py 各自定义 paradigm-local `AgentShapeCfg` / `CFRAgentShapeCfg`,
字段集相同(`n_counter_slots` / `n_hooks` / `max_tokens_per_hook` /
`max_actions` / `d_model` / `n_cross_layers` / `dropout`)但表面不同,
违反 spec invariant N1(ObsShape 单一 source of truth)。

| Paradigm | dataclass | 字段集 | 默认 d_model |
|---|---|---|---|
| AZ | `AgentShapeCfg` (in az/config.py) | 7 字段同语义 | 128 |
| BC | `AgentShapeCfg` (in bc/config.py) | 7 字段同语义 | 32 |
| CFR | `CFRAgentShapeCfg` | 7 字段同语义 | 64 |
| DMC | `AgentShapeCfg` (in dmc/config.py) | 7 字段同语义 | 32 |
| PPO | `PPOAgentShapeCfg` | 完全不同(d_model + n_hidden_layers + max_actions) | 256 |

`core/cfg/{shape.py, base.py}` 已在前 change Phase 1 ship 但
**0 paradigm 接入**。本 change 完成 4 paradigm(AZ/BC/CFR/DMC,PPO 暂不接)
的 ObsShape unification + ParadigmConfigBase compose + cfg version +
configs/<paradigm>/{default,smoke}.toml 模板。

PPO 不在本 change scope:`PPOAgentShapeCfg` 字段完全不同(flat MLP backbone),
统一 ObsShape 需要先做 PPO backbone migration(per D-101 deferred follow-up)。

## 2. What

**5 bullets**:

1. `core/cfg/base.py::ParadigmConfigBase` **drop `shape` field**(原假设 paradigm 用 ObsShape;但 paradigm 实际用 `agent: ObsShape` field name 以保持 caller `pcfg.agent.X` 兼容),只留 `version: str = '1.0.0'` + `paradigm: str = ''`
2. 新 `core/cfg/factories.py` — paradigm-specific shape factory functions(`make_az_default_shape()` / `make_bc_default_shape()` / `make_cfr_default_shape()` / `make_dmc_default_shape()` → `ObsShape`),defaults 从 paradigm 历史 `AgentShapeCfg` 移植
3. 4 paradigm config.py(`az` / `bc` / `cfr` / `dmc`):
   - `<X>ParadigmConfig` inherit `ParadigmConfigBase`(加 `version` + `paradigm` 字段)
   - `AgentShapeCfg = ObsShape` type alias(backward compat,paradigm test 不大改;CFR 类似)
   - `agent` field 类型改 `ObsShape`,`default_factory=make_<x>_default_shape`
   - `from_dict` 接受 `version` + `paradigm` 字段;若 toml 顶层 `meta.paradigm` 与 `[paradigm].paradigm` 不一致 → raise
4. 8 个 `configs/<paradigm>/{default,smoke}.toml` 模板(AZ/BC/CFR/DMC × 2)— `default.toml` 用 paradigm 历史 production 关键字段(参考 `_archived/active/`),`smoke.toml` 用 minimum viable(d_model=32 / 1 iter / max_steps 小)
5. 3 个 test 文件:`test_cfg_unification.py`(4 paradigm cfg inherit ParadigmConfigBase + agent 是 ObsShape) + `test_cfg_version_validation.py`(version / paradigm mismatch raise) + `test_obs_shape_factories.py`(4 factory 返回正确 defaults)

## 3. Affected specs

- `config-schema/spec.md` § ADD invariant N1 / N2 / N3(ObsShape unification + ParadigmConfigBase compose + version field 落地);spec status banner 更新 N5(configs/ layout)partial 完成(4 paradigm,not PPO)
- 无 paradigm-spec 修改:paradigm-<az/bc/cfr/dmc>/spec.md 字段集不变(ObsShape 与 AgentShapeCfg 字段名相同,只是 dataclass 来源换了)

## 4. Out of scope

- **PPO cfg 不动**(per D-202 paired deferred):`paradigms/ppo/config.py` 不触碰;`PPOAgentShapeCfg` 字段完全不同(flat MLP),unification 需先 ship PPO backbone migration follow-up(D-101)
- **不重写 paradigm 运行时代码**:`pcfg.agent.X` 访问 pattern 保留;type alias `AgentShapeCfg = ObsShape` 让 `bc/network.py` 等直接 import 不破
- **不改 `core/cfg/{shape,base}.py` 的 ObsShape 字段集**:本 change 假设 ObsShape 字段集已足够(7 字段),不扩展
- **不动 `_archived/` 子目录**:历史 toml 保留作 reference
- **不改 paradigm-local AgentShapeCfg 的 d_model defaults**(AZ=128 / BC=32 / CFR=64 / DMC=32):factory function 各自保留 paradigm 历史 default

## 5. Decision summary

- 字段名 `agent`(不是 `shape`)以保 caller 兼容,type alias `AgentShapeCfg = ObsShape`
- 4 paradigm 接入,PPO 不接(per D-202)
- `version: str = '1.0.0'` baseline,future cfg schema 改 bump
- `paradigm: str = '<x>'` subclass override 强制一致(load 期 toml `[paradigm].paradigm` 必须与 `[meta].paradigm` 一致,否则 raise)
- 8 toml(4 paradigm × 2 preset)— pre-redesign `active/` cfg 移植 production fields,smoke = d_model 32 + 1 iter
- 4 paradigm config_loader strictness:cfg toml `[paradigm]` 段必填 `version`,值 ∈ {'1.0.0'}(将来扩展);`paradigm` 必填,值必须与 `meta.paradigm` 一致
- Effort:~250 LOC(4 config.py edit + 1 factories.py new + 8 toml + 3 test)
