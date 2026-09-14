---
last_updated: 2026-05-16
status: DRAFT
schema_version: 0
capability: config-schema
change_id: unified-training-pipeline
---

# Spec delta — config-schema(new capability)

> 新 capability spec。GICG 训练侧 cfg(TOML)schema 与多层继承规约。本
> spec 锚定 `openspec-policy/spec.md` SHALL #7 + #13 落地实施。

## 1. Purpose

GICG cfg(`configs/*.toml`)字段散落各 paradigm,fallback 规则不一致,
typo / 缺段 / dead field 难诊断。本 spec 统一治理:

- **多层继承**:`device` / `seed` 按 fallback chain 解析,registry-driven
- **Placement schema**:R1-R7 七条 SHALL 保 inference cfg 闭合
- **Paradigm-specific 段**:`[paradigm]` 段 schema 由 `meta.paradigm` 决定
- **Loader strictness**:unknown / missing field → raise,no silent default

## 2. Scope

**In scope**:
- TOML cfg 顶层段定义(`meta` / `pipeline` / `eval` / `scenario` / `paradigm`)
- INHERITED_FIELDS registry(`device` / `seed`)实施 SHALL
- Placement R1-R7 schema(`pipeline.inference` + `eval.inference`)
- Cfg loader strictness 规约(unknown / missing field 行为)
- Seed derivation(blake2s-based)规约

**Out of scope**:
- Paradigm-specific cfg 字段(epsilon / lr / batch_size 等)→ 各
  `paradigm-<name>/spec.md`
- Cfg presets(default cfg combos)→ `training/core/config/presets.py`
  实施;spec 只锚定 path
- Scenario cfg(pool / team / max_rounds)→ 待落地 `runs-registry`
  capability spec

## 3. Core SHALL invariants

### CS1. 顶层段与必填字段

1. **CS1.1** Cfg 顶层 SHALL contain segments `meta` / `pipeline` /
   `scenario` / `paradigm`;`eval` SHALL be present if `pipeline.mode =
   "async"`,MAY be optional for `serial` smoke。
2. **CS1.2** `meta.seed` SHALL be present;NO hard default;missing →
   loader SHALL raise `"meta.seed required"`(per openspec-policy SHALL
   #13)。
3. **CS1.3** `meta.paradigm` SHALL be present,enum ∈ {`az`, `dmc`,
   `cfr`, `ppo`, `bc`}(case-sensitive);未知 paradigm name → raise。
4. **CS1.4** `meta.device` MAY be present;hard default `"cpu"`;enum ∈
   {`cpu`, `cuda`, `cuda:<N>`, `mps`}(per openspec-policy SHALL #13)。

### CS2. INHERITED_FIELDS registry(device + seed)

5. **CS2.1** INHERITED_FIELDS SHALL be the single source of truth at
   `training/core/config/inheritance.py`;新继承字段 SHALL through
   OpenSpec change(spec + impl 同步)。
6. **CS2.2** Device inheritance mode = `fallback`,fallback chain:
   - `pipeline.learner.device` → `meta.device`
   - `pipeline.inference.device` → `meta.device`
   - `pipeline.inference.remote.device` → `pipeline.inference.device` →
     `meta.device`
   - `eval.inference.device` → `meta.device`
   - `eval.inference.remote.device` → `eval.inference.device` →
     `meta.device`
7. **CS2.3** Seed inheritance mode = `fallback+derive`,no hard default;
   per-role seed derived via blake2s:`seed_role = master_seed ^ blake2s_4byte("{role}/{instance_id}")`,
   roles ∈ {`learner`, `actor`, `eval_scenario`, `eval_worker`}。

### CS3. Placement R1-R7(inference cfg 闭合)

8. **CS3.1 (R1)** `placement` SHALL be required field of any
   `[*.inference]` section,enum ∈ {`local`, `remote`}(case-sensitive)。
9. **CS3.2 (R2)** `placement == "local"` ⟺ NO `[*.inference.remote]`
   subsection;两者必须同时成立或同时不成立,否则 raise。
10. **CS3.3 (R3)** `placement == "remote"` ⟺ `[*.inference.remote]`
    subsection present AND `pool_size` + `max_batch` + `batch_timeout_ms`
    全部填写;任一缺失 → raise。
11. **CS3.4 (R4)** InferenceCfg 顶层字段 SHALL be closed set
    `{placement, device, version_tag, remote}`;额外顶层字段(如 typo'd
    `pool_size`)→ raise `"unknown field in InferenceCfg"`。
12. **CS3.5 (R5)** Device 全链路 None(meta / inference / remote 三层都
    省)→ raise `"device unresolved"`(不静默兜底 `cpu`,因为可能掩盖
    cfg bug)。
13. **CS3.6 (R6)** `extends` 继承时 placement override SHALL 同步子段:
    child cfg 改 `placement = "remote"` 但未提供 `[remote]` 段 → raise。
14. **CS3.7 (R7)** InferenceCfg dataclass 定义 SHALL =
    `InferenceCfg(placement, device, version_tag, remote: Optional)`;
    无 dead field 残留,无 `_legacy_*` 字段。

### CS4. Loader strictness

15. **CS4.1** Cfg loader SHALL raise on **unknown field**(任何 TOML key
    不在 dataclass schema)— typo 不静默忽略。
16. **CS4.2** Cfg loader SHALL raise on **missing required field**(per
    dataclass `field(default=MISSING)`)— 不替缺失 required 兜底任意值。
17. **CS4.3** Cfg loader SHALL support `extends = "<path>"` 引用 base cfg
    + override(深 merge),override 字段以 child 为准;但 R6 placement
    一致性 SHALL 验证。
18. **CS4.4** Paradigm-specific `[paradigm]` 段 schema SHALL by
    `meta.paradigm` 决定;loader SHALL dispatch to paradigm cfg dataclass
    (e.g. `DMCConfig` / `AZConfig`)+ same strictness rules apply。

## 4. Example cfg(non-normative,示例)

```toml
[meta]
seed = 42
device = "cpu"
paradigm = "dmc"
run_label = "r013_dmc_v_phase2_stage3"

[pipeline]
mode = "async"
num_actors = 24

[pipeline.inference]
placement = "local"
version_tag = "latest"
# device 省略 → fallback meta.device = "cpu"

[pipeline.learner]
# device 省略 → fallback meta.device = "cpu"

[eval]
n_workers = 4

[eval.inference]
placement = "local"
version_tag = "snapshot_eval"

[scenario]
pool = "v_phase2"
team_0 = ["凯亚"]
team_1 = ["凯亚"]
max_rounds = 15
deck_padding = { card = "碌碌无为", target_size = 15 }

[paradigm]                      # schema 由 cfg.meta.paradigm = "dmc" 决定
epsilon = 0.01
batch_size = 32
buffer_cap = 100_000
lr = 1e-4
weight_decay = 1e-4
```

## 5. Cross-references

- OpenSpec policy → [`../../../../../specs/openspec-policy/spec.md`](../../../../../specs/openspec-policy/spec.md)
  SHALL #7 + #13
- Inheritance registry impl → `training/core/config/inheritance.py`
- 主 training architecture → [`../../../../../specs/training-architecture/spec.md`](../../../../../specs/training-architecture/spec.md)
  SHALL #8(cfg 多层继承)
- Placement R1-R7 design → [`../../design/config-layered.md`](../../design/config-layered.md)
- Phase 3 实施 → [`../../tasks/phase3-core-dmc.md`](../../tasks/phase3-core-dmc.md) §3

## 6. Status

- **Created**:2026-05-16(本 change ship 时新建 capability)
- **Version**:0(初始)
- **Implementation**:Phase 3 落地(P3-T2 config layer)
- **Revision triggers**:
  - 新继承字段加入(超出 device + seed)→ INHERITED_FIELDS registry 更新
  - 新 paradigm 加入(超出 5 个)→ `meta.paradigm` enum 扩展
