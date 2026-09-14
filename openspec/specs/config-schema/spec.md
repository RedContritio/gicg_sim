---
last_updated: 2026-05-17
status: LIVE
schema_version: 0
capability: config-schema
---

# Config Schema — 训练 cfg TOML 字段 + 多层继承规约

> GICG 训练侧 cfg(TOML)schema 与多层继承规约。本 spec 锚定
> [`../openspec-policy/spec.md`](../openspec-policy/spec.md) SHALL #7 +
> #13 落地实施。

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

### CS5. 共享 shape + paradigm cfg base + cfg version + ckpt schema + configs layout

> Added by `core-network-generic-promotion` (archived 2026-05-17) — 5 paradigm
> 共享 obs shape + paradigm cfg base + cfg version 字段 + ckpt self-describing
> schema + configs/ 按 paradigm 一级组织。R1/R2 旧字段(paradigm-local
> AgentShapeCfg / 旧 ckpt schema)SUPERSEDED — 见 CS5 ↓ 与 archive
> `core-network-generic-promotion/`。

19. **CS5.1 (N1) ObsShape unification**:`training/core/cfg/shape.py::ObsShape`
    SHALL be 5 paradigm 共享的 obs shape dataclass:

    ```python
    @dataclass(frozen=True)
    class ObsShape:
        n_counter_slots: int
        n_hooks: int
        max_tokens_per_hook: int
        max_actions: int
        d_model: int = 128
        dropout: float = 0.0
        n_cross_layers: int = 2
    ```

    Paradigm cfg(`AZParadigmConfig` 等)SHALL compose `ObsShape` 作 `shape`
    字段,SHALL NOT 维护 paradigm-local 替代(如 `AgentShapeCfg` /
    `CFRAgentShapeCfg` / `PPOAgentShapeCfg`)。

20. **CS5.2 (N2) ParadigmConfigBase**:`training/core/cfg/base.py::
    ParadigmConfigBase` SHALL be 所有 paradigm cfg 的 base:

    ```python
    @dataclass(frozen=True)
    class ParadigmConfigBase:
        version: str = "1.0.0"          # cfg schema version, MUST bump on schema change
        paradigm: str = ""              # 'az' | 'bc' | 'cfr' | 'dmc' | 'ppo'
        shape: ObsShape = ...
    ```

    5 paradigm `<Paradigm>ParadigmConfig` SHALL 继承或 compose 这个 base。

21. **CS5.3 (N3) cfg version contract**:每个 `<Paradigm>ParadigmConfig`
    SHALL include `version: str` 字段,SHALL 默认为 `"1.0.0"`。Cfg schema
    任何字段增减 / 类型改 / 默认值改 SHALL trigger version bump。Load 时
    SHALL 校验 `ckpt['cfg_version'] == current_cfg.version`,不匹配 SHALL
    raise clear `CfgVersionMismatchError`,SHALL NOT silent shape-mismatch
    at forward time。

22. **CS5.4 (N4) Ckpt self-describing schema**:`torch.save` SHALL store
    complete metadata blob:

    ```python
    {
        'paradigm': str,                # 'az' | ...
        'cfg_version': str,             # e.g. '1.0.0'
        'cfg': dict,                    # asdict(cfg), full reconstructable
        'net_kind': str,                # 'ActorCritic' | ...
        'net_state_dict': OrderedDict,  # nn.Module.state_dict()
        'git_commit': str,              # subprocess.check_output(['git', 'rev-parse', 'HEAD'])
        'created_at': str,              # iso8601 UTC
    }
    ```

    `tools/ckpt/info.py` SHALL provide CLI to dump metadata without loading
    nn.Module(纯 dict inspection)。**旧 ckpt schema**(`{'net':
    state_dict, 'cfg': vars(cfg)}` 无 paradigm / cfg_version 字段)SHALL
    NOT 再支持 — load 旧 ckpt SHALL raise `CkptSchemaError`,SHALL NOT
    silently downgrade(supersedes 历史 ckpt schema)。

23. **CS5.5 (N5) configs/ layout**:TOML cfg files SHALL be organized by
    paradigm as primary axis:

    ```
    configs/<paradigm>/
    ├── default.toml          # 标杆 / 参考
    ├── smoke.toml            # smoke test 用
    └── runs/
        └── <run_id>.toml     # per-production-run cfg(reproducibility source)
    ```

    SHALL NOT 使用生命周期扁平结构(旧 `configs/{active,shipped,smoke,_archived}/`)。
    N5.5(PPO configs/)2026-05-17 起 5/5 complete + hybrid layout 详节见
    subtopic `obs-shape-unification.md` / `hybrid-toml-layout.md`。

### CS6. Hybrid TOML layout(`[shape]` + `[paradigm.<name>.X]`)

> Added by `cfg-toml-restructure-paradigm-scoped`(archived 2026-05-17)—
> hybrid 结构统一 5 paradigm cfg toml layout,dispatch via `meta.paradigm`,
> 非 dispatched paradigm section silent ignored。

24. **CS6.1 (N6) hybrid TOML layout**:5 paradigm cfg toml SHALL 通过
    hybrid 结构(`[shape]` global + `[paradigm.<name>.<sub>]` nested)统一,
    dispatch via `meta.paradigm`。完整 SHALL N6.1-N6.7 + `load_paradigm_cfg`
    helper + DECISIONS 详见 [`./hybrid-toml-layout.md`](./hybrid-toml-layout.md)。

## 4. Subtopics

本 capability 由本文件 + 2 个 subtopic 组成。主 spec.md 列 SHALL invariant
概要(CS5.1-CS5.5 已 merge by parent change `core-network-generic-promotion`,
CS6.1 已 merge by `cfg-toml-restructure-paradigm-scoped`),细化 detail
落 subtopic:

- [ObsShape unification + cfg version](./obs-shape-unification.md) —
  `ObsShape` SoT + `ParadigmConfigBase` (version + paradigm) + cfg version
  closed enum validation + `configs/<paradigm>/{default,smoke}.toml` 5 paradigm
  标准 layout。完整 N1.1-N5.5 + DECISIONS 见 subtopic。PPO 已接入
  (`ppo-structural-backbone-migration` archive 2026-05-17),CC-206 RESOLVED。
- [Hybrid TOML layout](./hybrid-toml-layout.md) —
  hybrid 结构:`[shape]` global + `[paradigm.<name>.<sub>]` nested,dispatch
  via `meta.paradigm`,非 dispatched section silent ignored。完整 N6.1-N6.7 +
  `load_paradigm_cfg` helper + toml 例子(含 PPO override)见 subtopic。

## 5. Example cfg(non-normative,示例)

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
# F4 (optional): explicit per-player decks — card-name multiset, 每名
# SHALL 已在 card_pool/pool 声明集中。缺省 = 隐式 eligible-set 路径,
# eligible > target_size 时引擎 fail-loud(无静默截断)。
# deck_0 = ["佛跳墙", "占星", ...]
# deck_1 = ["佛跳墙", "守正", ...]

[paradigm]                      # schema 由 cfg.meta.paradigm = "dmc" 决定
epsilon = 0.01
batch_size = 32
buffer_cap = 100_000
lr = 1e-4
weight_decay = 1e-4
```

## 6. Cross-references

- [`./obs-shape-unification.md`](./obs-shape-unification.md) — § 3 CS5 SHALL detail
  (N1.1-N5.5 ObsShape + ParadigmConfigBase + cfg version + configs layout)
- [`./hybrid-toml-layout.md`](./hybrid-toml-layout.md) — § 3 CS6 SHALL detail
  (N6.1-N6.7 hybrid TOML `[shape]` + `[paradigm.<name>.X]` + load_paradigm_cfg
  helper + dispatch + override + ignore semantics)
- OpenSpec policy → [`../openspec-policy/spec.md`](../openspec-policy/spec.md)
  SHALL #7 + #13
- Inheritance registry impl → `training/core/config/inheritance.py`
- 主 training architecture → [`../training-architecture/spec.md`](../training-architecture/spec.md)
  SHALL #8(cfg 多层继承)
- Originating change(archived)→
  [`../../changes/archive/unified-training-pipeline/`](../../changes/archive/unified-training-pipeline/)

## 7. Status

- **Created**:2026-05-16(unified-training-pipeline P6 archive)
- **Revised**:2026-05-17(`core-network-generic-promotion` archive)— +5
  SHALL N1-N5(CS5.1-CS5.5):ObsShape unification + ParadigmConfigBase + cfg
  version + ckpt self-describing schema + configs/<paradigm>/ layout。旧
  paradigm-local AgentShapeCfg + 无 paradigm/cfg_version 字段 ckpt schema
  SUPERSEDED(详 CS5.4 与 archive
  `core-network-generic-promotion/proposal.md`)。
- **Revised**:2026-05-17(`cfg-schema-unification` archive)— CS5.1/CS5.2/
  CS5.3/CS5.5 detail SHALL(N1.1-N3.4 + N5.1-N5.5)落地到新 subtopic
  `obs-shape-unification.md`(N4 仍由 parent CS5.4 持有);spec.md 加 §4
  Subtopics 索引 from scratch。详 archive
  `cfg-schema-unification/design.md`。
- **Revised**:2026-05-17(`cfg-toml-restructure-paradigm-scoped` archive)—
  +1 SHALL CS6.1(N6 hybrid TOML layout)summary + 新建
  `hybrid-toml-layout.md` subtopic 承接 N6.1-N6.7 全部 detail(7 SHALL +
  PPO override 例子 + load_paradigm_cfg helper);旧 § 7 N5.5 PPO ship
  status update(已 5/5 complete);Subtopics index 加 hybrid-toml-layout
  entry。详 archive `cfg-toml-restructure-paradigm-scoped/design.md`。
- **Version**:0(初始)
- **Implementation**:Phase 3 落地(P3-T2 config layer)
- **Revision triggers**:
  - 新继承字段加入(超出 device + seed)→ INHERITED_FIELDS registry 更新
  - 新 paradigm 加入(超出 5 个)→ `meta.paradigm` enum 扩展
