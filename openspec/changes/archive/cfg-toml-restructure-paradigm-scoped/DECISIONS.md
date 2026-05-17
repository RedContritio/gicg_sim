# cfg-toml-restructure-paradigm-scoped — autonomous decisions log

User 2026-05-17 授权"自主拍板"。本文件记录自主决策点,留给后续 review,decisions 标 [CC-NNN] 编号便于引用。

---

## Phase 1 propose autonomous decisions

### [CC-301] Hard break — 旧 flat [paradigm] toml load → raise

- **Decision**: 旧 flat `[paradigm]` scalar 字段(`lr = 1e-3` 直接 under `[paradigm]`)load 时 raise 清晰 error,指向 hybrid 结构。不留向后兼容垫片 / auto-convert / 双 schema 并存。
- **Why**:
  - User CLAUDE.md "不接受变通方案" + "废弃子系统时全量删除,不接受并行栈、迁移垫片"。
  - Silent auto-convert 违反"严格契约,错误可见"。
  - 本 repo 仅 8 existing toml(都在 worktree owned by 本 change)+ 2 新 PPO toml,user-facing migration burden = 0。
- **Spec impact**: config-schema/spec.md N6.x SHALL "legacy flat [paradigm] structure → raise"。
- **Follow-up**: future `tools/cfg/migrate.py` 可作外部 helper(out of scope)。

### [CC-302] PPO toml [shape] d_model=128 + [paradigm.ppo.agent] d_model=256 override

- **Decision**: PPO `configs/ppo/default.toml` 用共享 `[shape] d_model=128` + `[paradigm.ppo.agent] d_model=256` 显示 override 能力。
- **Why**:
  - PPO 历史 production d_model=256(per `PPOAgentShapeCfg.d_model` default);其它 4 paradigm production d_model ∈ {128, 64, 32}(per cfg-schema-unification CC-207)。
  - 在 toml 中显式 override 能让 user 一眼看出 PPO 偏离共享 schema 的位置;同时验证 override 实现正确。
  - Smoke toml `d_model=32` 也用 override(per CC-202 smoke 风格)。
- **Spec impact**: 无 invariant 改动(纯 config 决策);例子用在 spec 例子段。

### [CC-303] Override 实现 = dict merge,不是 dataclass replace

- **Decision**: loader 用 `{**shape_dict, **paradigm_agent_dict}` dict merge,不用 `dataclasses.replace(shape_obj, **agent_dict)`。
- **Why**:
  - Dict merge 简洁(2 行);loader 不 import ObsShape dataclass,降低 cross-paradigm coupling。
  - Validation 留给 paradigm.from_dict → build_shape_from_toml(已有 strict unknown-key validation per cfg-schema-unification)。
  - dataclass replace 需先构造 default → 引入隐式 sequence dependency。
- **Spec impact**: 无;实现细节。

### [CC-304] [paradigm.<wrong_name>] silent ignored

- **Decision**: dispatch `meta.paradigm = "ppo"` 时,toml 中 `[paradigm.az.X]` / `[paradigm.bc.X]` 等其它 paradigm 段 silent ignored(不 raise / 不 warn)。
- **Why**:
  - 允许 single toml 写多 paradigm cfg 作 reference / cross-compare / ablation。
  - 不阻断 future "single toml 多 paradigm dispatch" 用法(e.g. tournament runs 加载同 toml 跑 5 paradigm)。
  - Spec N6.3 已说明 dispatch 只看 meta.paradigm,其它段 unused。
- **Spec impact**: config-schema/spec.md N6.3 SHALL "non-dispatched [paradigm.<other>] section ignored"。
- **Follow-up**: future `--strict` mode 可加 raise on unused;本 change 不实现。

### [CC-305] [shape] 顶层段可选,缺则 factory default

- **Decision**: `[shape]` 顶层共享段是 OPTIONAL;若缺,paradigm `agent` field 用 `make_<X>_default_shape()` factory default(per cfg-schema-unification N1.2);存在则 merge 进 paradigm.agent dict。
- **Why**:
  - smoke toml 不需写全量 obs schema,factory default 足以让 smoke pipeline alive。
  - 强制 `[shape]` = 8 toml 都重复写相同 7 字段,纯噪声。
  - Factory default 已是 spec invariant(N1.2),复用之。
- **Spec impact**: config-schema/spec.md N6.4 SHALL "[shape] optional;missing → paradigm factory default"。

### [CC-306] Loader 位置 = `core/cfg/loader.py` shared helper

- **Decision**: 新 `load_paradigm_cfg` helper 放 `training/core/cfg/loader.py`(与 ParadigmConfigBase + factories 同 dir),5 paradigm 共用;不在各 paradigm `config_loader.py` 各自实现。
- **Why**:
  - 5 paradigm helper 行为完全相同(extract `[paradigm.<name>]` + merge `[shape]`)— 重复 5 次违反 DRY。
  - `core/cfg/` 已是 paradigm-agnostic cfg primitives 集合点(ObsShape + ParadigmConfigBase + factories);loader 同性质。
  - 入口仍是 `core/config/loader.py::load_cfg`(unified pipeline loader);`core/cfg/loader.py` 是 sub-step helper。
- **Spec impact**: config-schema/spec.md N6.5 SHALL "`load_paradigm_cfg` is shared helper in core/cfg/loader.py"。
- **Follow-up**: future 若有 paradigm-specific hybrid quirk,可在 paradigm `config_loader.py` 包装。

### [CC-307] Spec delta merge 推迟到 archive workflow

- **Decision**: 本 change 落 `openspec/changes/cfg-toml-restructure-paradigm-scoped/specs/config-schema/spec.md` 是 delta;archive workflow 跑 5-step SOP 时 merge 到 `openspec/specs/config-schema/spec.md` 主 spec。
- **Why**: 与 cfg-schema-unification CC-209 + core-network-generic-promotion D-401 一致,避免在 change 实施期手动 merge spec deltas 违反 single source of truth。
- **Spec impact**: 主 spec.md 暂不更新;delta merge 在 archive 后。

### [CC-308] Dispatch selector 仍走 meta.paradigm,不引入 top-level `paradigm = "..."` scalar

- **Decision**: 原 task description 提到 "top-level `paradigm = "ppo"` 字段选哪个 [paradigm.<name>] 段" — 拒绝。TOML 不允许 scalar `paradigm = "ppo"` 与 section `[paradigm.X]` 同 path 共存(语法冲突)。dispatch 仍走 `meta.paradigm`(unchanged from current loader)。
- **Why**:
  - TOML spec 限制:`paradigm = "ppo"` + `[paradigm.ppo]` 二选一,不可同时。
  - `meta.paradigm` 已是 current dispatch selector(unified loader 三 change ago ship),改名增加 churn。
  - 在 [meta] 第三行 vs toml 第一行 — readability cost 小。
- **Spec impact**: 无 invariant 改动;design.md 例子统一用 `meta.paradigm`。
- **Follow-up**: future 若要 top-level selector,rename section 至 `[paradigms.X]`(plural)+ `paradigm = "X"` scalar(独立 change)。

### [CC-309] PPO 也接入 ObsShape unification

- **Decision**: 本 change `configs/ppo/{default,smoke}.toml` 也用 `[shape]` + `[paradigm.ppo.agent]` 结构,与 4 paradigm 对称。这意味着 PPO config dataclass 也需要 `from_dict` 接受 `agent` sub-dict + 字段 override semantics。
- **Why**:
  - Pre-requisite #4 `ppo-structural-backbone-migration` 已 ship,PPO `PPOAgentShapeCfg` 字段集与 ObsShape 完全对齐(`n_counter_slots / n_hooks / max_tokens_per_hook / max_actions / d_model / n_cross_layers / dropout`,7 字段)。
  - 本 change task spec 显式要求 PPO 2 新 toml — 必须 PPO from_dict 接受 agent sub-dict。
  - PPO 当前 `from_dict` 已实现 `PPOAgentShapeCfg(**agent_d)`,本 change 不改 PPO config code,只用 toml 把 [shape] + agent merge 后喂给现有 from_dict。
- **Spec impact**: cfg-schema-unification N1.4 注释 "PPO 暂不接 unification" 在本 change 后部分过时(toml 层 PPO 已接,但 dataclass type 仍是 `PPOAgentShapeCfg` ≠ `ObsShape`);**保留 N1.4 不动**(dataclass 仍未 unified)。`PPOAgentShapeCfg` → `ObsShape` 切换是 future change(out of scope)。
- **Follow-up**: 未来 cfg-schema-unification 续作可 retire `PPOAgentShapeCfg`,替换为 ObsShape;本 change 仅 toml 层接入。
