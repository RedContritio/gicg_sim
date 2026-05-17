# cfg-schema-unification — Design Retrospective

> Archive-time summary (≤ 200 lines per archive cap)。详细 Architecture +
> Migrations 内容已拆到 `design/` subdir,见 ↓ 索引。

## Verdict

**成功** — ObsShape unification + cfg version + ParadigmConfigBase compose
全部落地到 4 paradigm(AZ/BC/CFR/DMC),PPO defer 到 follow-up change
`ppo-structural-backbone-migration`(同日 2026-05-17 ship)。Parent change
`core-network-generic-promotion` 已 merge CS5.1-CS5.5 summary;本 change
将 detail SHALL(N1.1-N5.5)落到 `obs-shape-unification.md` subtopic,完成
parent placeholder → detail refinement 的 spec-level 闭环。

## What we built

- `core/cfg/base.py` rewrite — `ParadigmConfigBase` drop `shape` field
  (CC-203),只留 `version: str = '1.0.0'` + `paradigm: str = ''` metadata
  字段,subclass 通过 `agent: ObsShape` 字段表达 shape 契约
- `core/cfg/factories.py` new — 4 paradigm factory function
  (`make_<x>_default_shape`)保 paradigm 历史 production d_model
  (AZ=128 / BC=32 / CFR=64 / DMC=32)
- 4 paradigm `<X>ParadigmConfig` inherit `ParadigmConfigBase`,override
  `paradigm: str = '<x>'`,compose `agent: ObsShape = field(default_factory=
  make_<x>_default_shape)`
- 每 paradigm config.py 保留 `AgentShapeCfg = ObsShape` type alias(CC-202)
  + CFR 保留 `CFRAgentShapeCfg = ObsShape` — caller 0 改动
- 4 paradigm `from_dict` strict validation:`version` ∈ closed enum
  `{'1.0.0'}`(CC-204),`paradigm` mismatch raise(CC-205);unknown key
  仍 raise(沿用 CS4)
- 8 个新 toml:`configs/{az,bc,cfr,dmc}/{default,smoke}.toml`
  (default 用历史 production d_model,smoke 用 d_model=32 + max_steps=30)

详 [`design/architecture.md`](./design/architecture.md)。

## Tradeoffs revisited

- **CC-201/CC-202(field 名 `agent` vs `shape`)**:预期 + 实际 ✓ — 选
  `agent` 字段名保持 20+ runtime 访问点 0 改动(Option B),代价是字段名
  `agent` 与 type `ObsShape` 名称不对齐,稍 confusing 但远比 churn 30+
  文件好
- **CC-203(base drop `shape` field)**:预期 + 实际 ✓ — 与 CC-201 配对
  selection;base 字段集与 subclass 实际字段集对应,无 dead 字段
- **CC-204(version enum vs free string)**:预期 + 实际 enum ✓ — 符合
  spec "严格契约,错误可见";future bump 需显式 OpenSpec change
- **CC-206(PPO defer)**:预期 + 实际 defer ✓ — PPO 用 flat MLP backbone
  (非 structural),`PPOAgentShapeCfg` 字段集与 ObsShape 不兼容;defer 等
  `ppo-structural-backbone-migration` follow-up(同日 ship)
- **CC-208(smoke n_counter_slots=1832 not 66)**:实际 ✓ — 保持工程默认
  避免 smoke vs production 双轨;d_model=32 + max_steps=30 已足够 smoke
  pipeline alive verify

## Surprises

- **CFR isinstance test 自动通过**:`CFRAgentShapeCfg = ObsShape` alias
  后 `isinstance(cfg.agent, CFRAgentShapeCfg)` 仍 True(同一 class
  reference),0 test 改动
- **type alias 兼容性范围**:预期 alias 只为 import 兼容;实际 isinstance
  / `dataclasses.asdict` / `==` 全自动兼容 — Python alias 是直接 class
  reference 不是 wrapper
- **toml schema validation 0 production bug**:8 toml 一次 load 全通过,
  之前担心字段集错(AZ toml 写到 BC paradigm 字段)未发生 — 写 toml 时
  直接 copy paradigm config.py 字段列做参考,避免 manual typing

## Spec delta summary

本 change 修订 1 capability spec + 新建 1 subtopic:

- **config-schema**:
  - 新建 `obs-shape-unification.md` subtopic 承接 ADD § 7 全部 detail
    (N1.1-N5.5,5 段约 75 行 SHALL):
    - N1.1-N1.4 ObsShape SoT(`training/core/cfg/shape.py`)+ 4 paradigm
      compose pattern + AgentShapeCfg alias + PPO defer 范围限定
    - N2.1-N2.3 ParadigmConfigBase compose(version + paradigm 字段)+
      `shape` 字段 not in base
    - N3.1-N3.4 cfg version 字段 + closed enum `{'1.0.0'}` 校验 + paradigm
      mismatch raise + 空 dict from_dict 全 default 成功路径
    - N5.1-N5.5 configs/<paradigm>/{default,smoke}.toml(4/5 partial,PPO
      defer)+ smoke 最小 viable + `[paradigm]` 显式 version/paradigm key
  - `spec.md`:加 § 7 summary(4-6 行 + xref)+ 新建 Subtopics 索引
    section(从无到有);N4 跳过(parent CS5.4 已 merge ckpt schema)
  - Cross-references:CC-201..208(本 change DECISIONS)+ predecessor
    change DECISIONS D-201/D-202/D-204

## 索引

- **[`design/architecture.md`](./design/architecture.md)** — §1 Architecture
  + §2 Tradeoffs(ParadigmConfigBase rewrite / factories / 4 paradigm
  config.py / configs toml 模板 / config_loader strictness / 5 Option
  pros-cons)
- **[`design/migrations.md`](./design/migrations.md)** — §3 Migration phase
  顺序 + §3.2 backward-compat 表 + §3.3 test cascading + §4 Risks(PPO
  无影响 / ObsShape default 差异 / base drop shape BREAKING / toml typo)
  + §5 Rollback + §6 Verification matrix + §7 LOC estimate
