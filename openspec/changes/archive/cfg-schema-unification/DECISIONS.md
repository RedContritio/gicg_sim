# cfg-schema-unification — autonomous decisions log

User 2026-05-17 授权"自主拍板"。本文件记录自主决策点,留给后续 review,decisions 标 [CC-NNN] 编号便于引用。

---

## Phase 1 propose autonomous decisions

### [CC-201] Shape field 命名 `agent`(不是 `shape`)

- **Decision**: paradigm config 用 `agent: ObsShape` 字段名,不用 `shape: ObsShape`。
- **Why**:
  - 4 paradigm 运行时代码(`dmc/paradigm.py:58-64` / `bc/paradigm.py:63-69` / `az/network.py` 等)已经 20+ 处用 `pcfg.agent.X` 访问。
  - Rename 至 `pcfg.shape.X` 是纯机械改动,30+ 文件 / 50+ 行 churn,zero 功能收益。
  - Type 已统一(ObsShape across 4 paradigm),spec invariant N1 "ObsShape 单一 source of truth" 已达成,与字段名无关。
- **Spec impact**: `config-schema/spec.md` N1 不强制字段名,只锚 dataclass type。
- **Follow-up**: 若未来希望字段名统一,作 single-purpose rename change(纯机械);本 change 不在 scope。

### [CC-202] `AgentShapeCfg = ObsShape` 类型别名保留

- **Decision**: 4 paradigm 各自的 `AgentShapeCfg` / `CFRAgentShapeCfg` 保留作 `ObsShape` 类型别名。
- **Why**:
  - `bc/network.py:21` 显式 `from training.paradigms.bc.config import AgentShapeCfg`,如果删除会破。
  - `test_az_paradigm_config_phase1.py` / `test_cfr_paradigm.py` 等多个 paradigm test import `AgentShapeCfg`(各自 paradigm 命名空间);Type alias 让 `isinstance(cfg.agent, AgentShapeCfg)` 仍 True。
  - 别名 = 0 LOC 维护成本,backward compat 0 风险。
- **Spec impact**: 无;ObsShape 仍是 SSOT。
- **Follow-up**: 别名可在未来 cleanup change 中移除(当所有 caller 改用 ObsShape direct import)。

### [CC-203] `ParadigmConfigBase` drop `shape` field

- **Decision**: `ParadigmConfigBase` 字段集减少到 `version` + `paradigm`,不含 `shape` field。
- **Why**:
  - 原 base 设计假设 subclass 用 `shape: ObsShape` 字段,但 CC-201 决定保留 `agent` 字段名。
  - 若 base 保 `shape` field,subclass 加 `agent` field,base 的 `shape` 就成 dead field(永不被使用),违反"无 dead field"原则。
  - Base 只需表达 paradigm-agnostic 元数据(version + dispatch key);shape 由 subclass 通过 `agent` field 提供。
- **Spec impact**: `config-schema/spec.md` N2 invariant 表述为 "ParadigmConfigBase compose version + paradigm fields,subclass 通过 typed shape field(name TBD)compose ObsShape"。
- **Follow-up**: 若决定字段名 unified,base 可重新加 shape field(单独 rename change)。

### [CC-204] Version 默认 `'1.0.0'`,enum validation

- **Decision**: 4 paradigm cfg `version: str = '1.0.0'` baseline;`from_dict` 验证 `version` ∈ `{'1.0.0'}` 闭集合。
- **Why**:
  - 闭集合 enum 让 typo(`'1.0'` vs `'1.0.0'`)立即 raise,符合"严格契约,错误可见"。
  - Free-form string 字段会让 user 写出 `'v1'` / `'1.0'` 等 variant,silent merge 风险。
  - Future cfg schema 改 bump = explicit OpenSpec change,符合 SHALL #7。
- **Spec impact**: `config-schema/spec.md` N3 SHALL "cfg version 字段必填 + enum validated"。
- **Follow-up**: 未来 cfg schema 改 → bump version `'1.1.0'` + 同步 `_VALID_VERSIONS` 集合。

### [CC-205] Paradigm 字段 mismatch raise(toml vs dataclass default)

- **Decision**: `from_dict({'paradigm': 'bc'})` on `AZParadigmConfig` → raise `'paradigm mismatch: expected az, got bc'`。
- **Why**:
  - `[paradigm].paradigm` 与 `[meta].paradigm` 不一致 = silent bug 风险。
  - 已有 `core/config/loader.py::_load_paradigm_validator` 按 `meta.paradigm` 路由到对应 from_dict;在 from_dict 加一层验证 = defense in depth。
- **Spec impact**: spec 无新约束,既有 dispatch 契约的明示化。

### [CC-206] PPO 不接 ObsShape unification(per D-202 deferred)

- **Decision**: `paradigms/ppo/config.py` 不触碰;`PPOAgentShapeCfg` 字段不变。
- **Why**:
  - `PPOAgentShapeCfg` 字段集完全不同(`d_model` + `n_hidden_layers` + `max_actions`,无 hook/counter),与 ObsShape 不兼容。
  - PPO 用 flat MLP backbone,不是 structural;ObsShape 假设 structural shape。
  - PPO backbone migration 是独立 sub-project(per D-101 follow-up `ppo-structural-backbone-migration`)。
- **Spec impact**: spec invariant N1 SHALL 仅适用 4 paradigm(AZ/BC/CFR/DMC),N1 文本明确 "5 paradigm 中除 PPO 外 4 个共享 ObsShape"。
- **Follow-up**: PPO backbone migration ship 后,本 change 的 spec invariant 自然扩展到 5 paradigm。

### [CC-207] Configs/<paradigm>/{default,smoke}.toml 内容选择

- **Decision**:
  - `default.toml`:用 paradigm 历史 production 字段(参考 `configs/_archived/pre_redesign_2026_05_17/{shipped,active}/`):
    - AZ: `_archived/shipped/fixed_1v1.toml` 参考(d_model=128 / mcts.n_rollouts=200 / lambda anneal)
    - BC: 参考 `_archived/smoke/smoke_bc_pretrain_container.toml`(d_model=32 / lr=1e-4 / loss_kind='ce')
    - CFR: 用 paradigm config defaults(d_model=64 / n_iterations=100)
    - DMC: 参考 `_archived/active/dmc_stage3.toml`(d_model=32 / epsilon=0.05 / total_frames=5000)
  - `smoke.toml`:统一 d_model=32 / n_iter=1 / total_games=2 / max_steps=30
- **Why**: production cfg 是已 ship 的 active baseline,smoke 用 minimum viable per task hint #4。
- **Spec impact**: 无;configs/ 是 cfg 文件,不是 spec。

### [CC-208] 不用 `n_counter_slots=66` smoke 简化

- **Decision**: smoke toml 用 production 工程默认 `n_counter_slots = 2*6*128 + 2*140 + 16 = 1832`,不缩小到 66。
- **Why**: env 与 counter slot 数有约束,从 1832 改 66 需对应改 env 启动(可能破 engine 假设);smoke 目标是 cfg load + paradigm config 构造,不是网络 inference,n_counter_slots 大小不影响 smoke pass。
- **Spec impact**: 无。

### [CC-209] Spec delta 不 merge live spec(deferred to archive workflow)

- **Decision**: 本 change 落 `openspec/changes/cfg-schema-unification/specs/config-schema/spec.md` 是 delta;archive workflow 跑 5-step SOP 时 merge 到 `openspec/specs/config-schema/spec.md` 主 spec。
- **Why**: 与 `core-network-generic-promotion` D-401 相同处理,避免在 change 实施期手动 merge spec deltas 违反 single source of truth。
- **Spec impact**: 主 spec.md 暂不更新;delta merge 在 archive 后。
