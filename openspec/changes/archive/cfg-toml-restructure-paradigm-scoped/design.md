---
last_updated: 2026-05-17
status: ARCHIVE
schema_version: 0
change_id: cfg-toml-restructure-paradigm-scoped
---

# cfg-toml-restructure-paradigm-scoped — Design Retrospective

> Archive-time summary(≤ 200 lines per archive cap)。详细 architecture +
> loader 改造 + 5 Option tradeoffs + risks / migration / verification matrix
> 已拆到 `design/` subdir,见 ↓ 索引。

## Verdict

**成功** — Hybrid TOML layout 全面落地:`[shape]` 顶层共享 +
`[paradigm.<name>.<sub>]` paradigm-scoped nested 段统一 5 paradigm
(AZ / BC / CFR / DMC / PPO)cfg toml layout,dispatch via `meta.paradigm`,
非 dispatched paradigm section silent ignored(允许 single toml 写多
paradigm 作 reference)。`load_paradigm_cfg` shared helper(`training/core/
cfg/loader.py`)由 `core/config/loader.py::load_cfg` 在 paradigm dispatch
validator 之前调用,merge `[shape]` → paradigm.agent(agent override per
dict merge,CC-303)。Hard break:旧 flat `[paradigm].lr=` scalar key →
loader raise clear error 指向 hybrid 结构(CC-301,no migration垫片)。

10 toml restructure(8 existing AZ/BC/CFR/DMC + 2 新 PPO)+ `core/cfg/
loader.py` 新 helper + `core/config/schema.py::ALLOWED_TOP_LEVEL` +
`'shape'` + `test_cfg_toml_hybrid.py` 新测试覆盖 6 invariants。Pre-requisite
两个 ship(`cfg-schema-unification` 5/5 paradigm cfg dataclass + `ppo-
structural-backbone-migration` PPO 字段对齐)就绪后 1 session 12/12 tasks
全部完成,~250-300 LOC 实施 + ~200 LOC test,9 个自主决策 CC-301..309
全部 archive-merged。

## What we built

- **`training/core/cfg/loader.py`** — new shared helper(CC-306):
  `load_paradigm_cfg(toml_dict, paradigm_name) -> dict` 提取
  `[paradigm.<name>]` 顶层 hparam + `[paradigm.<name>.X]` sub-sections
  成 flat dict,merge `[shape]` 进 agent(`{**shape, **agent}` dict merge,
  CC-303);检测 legacy flat `[paradigm].scalar = ...` → raise hard break
  指向 hybrid 结构(CC-301)
- **`training/core/cfg/__init__.py`** — export `load_paradigm_cfg`
- **`training/core/config/loader.py::load_cfg`** — 在 paradigm dispatch
  validator 之前 call `load_paradigm_cfg(resolved, paradigm)`,
  `_build_dataclass` 接受 `paradigm_flat` 参数
- **`training/core/config/schema.py::ALLOWED_TOP_LEVEL`** — `+ 'shape'`
  (顶层共享段 OPTIONAL per CC-305;缺则 paradigm factory default)
- **10 toml restructure**:
  - 8 existing(`configs/{az,bc,cfr,dmc}/{default,smoke}.toml`)— 旧 flat
    `[paradigm]` 顶层 hparam → `[paradigm.<name>]`;旧 `[paradigm.X]`
    sub-sections → `[paradigm.<name>.X]`;顶层 `[shape]` 段 OPTIONAL
    (smoke 不写用 factory default,default 写共享 d_model)
  - 2 新 PPO(`configs/ppo/{default,smoke}.toml`)— CC-302 显示 override:
    default `[shape] d_model=128` + `[paradigm.ppo.agent] d_model=256`;
    smoke `[paradigm.ppo.agent] d_model=32`
- **`training/tests/test_cfg_toml_hybrid.py`** — 新测试覆盖 6 invariants:
  5 paradigm dispatch / shape override / shape 缺 OK / paradigm 段缺 OK /
  legacy flat raise / wrong_name silent ignored / 10 toml load 全 alive /
  round-trip equivalence
- **Spec delta**(merged into `config-schema/`):MODIFY § 7 N5(PPO
  configs/ ship status update,与 ppo-structural-backbone-migration 合
  推到 5/5 complete)+ ADD § 8 N6 全部内容(N6.1-N6.7,7 SHALL)落
  `hybrid-toml-layout.md` subtopic

详 [`design/architecture.md`](./design/architecture.md)(架构 + loader
+ schema + 5 Option pros/cons)。

## Tradeoffs revisited

- **CC-301(hard break vs migration tool)**:预期 + 实际 hard break ✓ —
  本 repo 仅 8 existing toml + 2 新 PPO toml(全在 worktree owned by 本
  change),user-facing migration burden = 0;silent auto-convert 违反"严格
  契约,错误可见"
- **CC-302(PPO toml [shape]=128 + [paradigm.ppo.agent]=256 override)**:
  预期 + 实际 ✓ — 让 PPO 历史 d_model=256 在 toml 中显式 override 共享
  `[shape] d_model=128`,validation override 实现正确;PPO test 验证
  effective d_model=256
- **CC-303(dict merge vs dataclass replace)**:预期 + 实际 dict merge ✓ —
  loader 不 import ObsShape dataclass,降低 cross-paradigm coupling;
  validation 留给 paradigm.from_dict / build_shape_from_toml
- **CC-304(non-dispatched paradigm silent ignored vs raise)**:预期 + 实际
  silent ignored ✓ — 允许 single toml 写多 paradigm cfg 作 reference /
  cross-compare / ablation;future `--strict` mode 可加 raise on unused
- **CC-305([shape] optional vs required)**:预期 + 实际 optional ✓ —
  smoke toml 不需写全量 obs schema,factory default 足以 smoke pipeline
  alive verify
- **CC-306(loader 位置 shared in core/cfg vs paradigm-local)**:预期 +
  实际 shared ✓ — 5 paradigm helper 行为完全相同(extract + merge),
  paradigm-local 实现违反 DRY 5×
- **CC-308(dispatch selector `meta.paradigm` 不引入 top-level scalar)**:
  Option A(top-level `paradigm = "ppo"` scalar)REJECTED ✓ — TOML 不允许
  scalar 与 section 同 path(`paradigm = "ppo"` + `[paradigm.X]` 冲突);
  `meta.paradigm` 已是 selector,不重复
- **CC-309(PPO 也接入 hybrid toml)**:预期 + 实际 ✓ — pre-requisite
  `ppo-structural-backbone-migration` 字段对齐后 PPO `from_dict` 已接受
  `agent` sub-dict;本 change 仅 toml 层接入,PPO `PPOAgentShapeCfg` →
  `ObsShape` dataclass alias 切换是 future change(out of scope)

## Surprises

- **`meta.extends` 不冲突**:开工时 concern hybrid 结构与 `meta.extends`
  cfg 继承会有交互;实际 `_apply_overrides` + `_load_with_extends` 都在
  raw toml 层面 work,`load_paradigm_cfg` 仅作 dispatch 前 step,语义独立
- **5 paradigm `from_dict` 字段对齐 0 改动**:开工时担心 5 paradigm
  `from_dict` 接受不同 sub-dict 结构 — 实际 `cfg-schema-unification` +
  `ppo-structural-backbone-migration` ship 后 5 paradigm `agent` field 名
  统一 + 字段集对齐,本 change 仅改 toml 层,paradigm cfg code 0 改动
- **legacy flat detection 简洁**:CC-301 hard break 实现仅 2 行
  `non_dict_keys = [k for k, v in pdict.items() if not isinstance(v, dict)]`
  即可识别 legacy scalar,无需 schema introspection / 字段 enum 对比

## Spec delta summary

本 change 修订 1 capability spec + 新建 1 subtopic:

- **config-schema**:
  - 新建 `hybrid-toml-layout.md` subtopic 承接 ADD § 8 N6 全部 detail
    (N6.1-N6.7,7 SHALL):
    - N6.1 paradigm block nested structure(no scalar under [paradigm],
      legacy flat raise)
    - N6.2 dispatch via meta.paradigm(no top-level scalar conflict)
    - N6.3 non-dispatched paradigm silent ignored(允许 multi-paradigm
      reference toml)
    - N6.4 `[shape]` optional default(factory default fallback,agent
      override per-field dict merge)
    - N6.5 `load_paradigm_cfg` shared helper(`core/cfg/loader.py`)
    - N6.6 `ALLOWED_TOP_LEVEL` + `'shape'`
    - N6.7 详细 toml 例子(含 PPO `[shape]=128 + [paradigm.ppo.agent]
      =256` override)
  - `spec.md`:加 § 3 CS6.1 summary(4-6 行 + xref)+ Subtopics index
    entry(2 个 subtopic 索引)+ Status section Revised entry;§ 7 CS5.5
    注 PPO 5/5 complete(原 partial 状态 RESOLVED by
    `ppo-structural-backbone-migration` predecessor)
  - Cross-references:CC-301..309(本 change DECISIONS)+ predecessor
    change DECISIONS D-501(`core-network-generic-promotion`)

## 索引

- **[`design/architecture.md`](./design/architecture.md)** — §1 Architecture
  (hybrid TOML structure / load_paradigm_cfg helper / schema 改动)+
  §2 Tradeoffs(5 Option pros-cons + REJECTED reasons)
- **[`design/migrations.md`](./design/migrations.md)** — §3 Migration phase
  顺序(T0-T10)+ §3.2 test cascading + §4 Risks(4 risks:cfg.paradigm
  flat dict / CLI override path / shape override priority / PPO d_model
  default vs override)+ §5 Rollback + §6 Verification matrix + §7 LOC
  estimate
