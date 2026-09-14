---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: engine-dsl
---

# Engine DSL — author-facing 约定与 Builtin API 规约

> GICG 游戏机制(角色 / 卡 / 状态 / 反应 / 护盾)以 Lua syntax 子集
> 描述,运行在 `gicg_engine/interp/` 的原生 AST 解释器上。本 capability
> spec 治理 DSL 作者面向的约定与 builtin API 接口契约。
>
> Engine runtime 行为(`Runtime.LoadFilesWithDeps` 拓扑加载 /
> `Runtime.ExecFileSandboxed` 隔离 / DSL load cache)在主 spec 用
> cross-reference 指向,详细规约留待 engine-runtime spec 落地后迁移。

## 1. Purpose

DSL 是 engine 与 game data 之间唯一的契约层。Engine ignorant of HP / energy
/ elements / shields(详 `CLAUDE.md "Engine Ignorance"`),所有 game term
通过 counter + hook 在 DSL 中表达。本 spec 提供 6 大类约束:

- **Counter 系统**(详 [`./counter.md`](./counter.md))
- **Hook dispatch**(详 [`./hook.md`](./hook.md))
- **Damage pipeline**(详 [`./damage.md`](./damage.md))
- **Skill pattern**(详 [`./skill-pattern.md`](./skill-pattern.md))
- **Builtin API + Lua subset**(详 [`./builtin-api.md`](./builtin-api.md))
- **File structure**(详 [`./file-structure.md`](./file-structure.md))

## 2. Scope

**In scope**:
- `data/` 下所有 `.lua` 文件作者面向约定(counter 用法 / hook 写法 /
  skill / card pattern / shield 形态)
- DSL 中可用的 Lua 子集与禁止构造
- `gicg_engine/interp/builtins.go` 暴露的 builtin function 签名与语义
- mirror match / talent / shared-load 等 file-isolation 边界规则
- DSL-Go ref 类型契约(`*SkillRef` / `*CardRef` / Lazy proxy)

**Out of scope**:
- Engine runtime 加载顺序的具体算法(拓扑排序实现细节)— engine-runtime spec
- `gicg_engine/` 内部 counter / hook 实现的数据结构 — engine-runtime spec
- Python 训练侧 obs / action 编码 — RL training spec
- `data/pools/<pool_id>/` 卡池版本治理 — pool-versioning spec(ADR-0011 落地)

## 3. Core SHALL invariants

以下 15 条 invariant 是本 capability 的硬约束。任意冲突应作为 OpenSpec
change 提案修订,而非在 DSL 文件中静默偏离。

1. **DSL 加载**:DSL files SHALL be loaded via
   `gicg_engine/interp/Runtime.LoadFilesWithDeps`(按 declare/get 关系拓扑
   排序)。详 engine-runtime spec(待落地)。

2. **Counter 使用规则**:Counters SHALL represent persistent game state
   that the engine does not already track。SHALL NOT shadow engine-managed
   data(hands / decks / chars alive / turn / round)。SHALL NOT model
   transient state within a single event chain。详 [`./counter.md`](./counter.md)。

3. **Counter declare-or-get**:Counters SHALL be declared with
   `declare_counter(name, scope, value, {min, max, tag})` and accessed via
   `get_counter(name, scope[, bind])`。Declare-or-get 语义:重复 declare
   参数 SHALL 完全一致,否则 engine SHALL panic。详 [`./counter.md`](./counter.md)。

4. **Counter scope 枚举**:Counter scope SHALL be one of `Self` /
   `ActiveStatus` / `PerPlayer` / `PerChar` / `Global`。每 scope 的 key 结构
   与 access API 详 [`./counter.md`](./counter.md)。

5. **Hook dispatch**:Hook 注册 SHALL provide `HookType`(派发分类)+ 可选
   Priority(数字越大越先;同 priority 按注册顺序)。详 [`./hook.md`](./hook.md)。

6. **Hook filter 语义**:Hook callbacks SHALL filter by `ctx.*` early-return,
   SHALL NOT 依赖 Go-side filter matching。详 [`./hook.md`](./hook.md)。

7. **Damage pipeline 顺序**:Damage pipeline SHALL run 5 phases in order:
   `on_damage_boost` → `on_reaction_damage` → `on_damage_reduce` → HP write
   → `on_after_damage`。详 [`./damage.md`](./damage.md)。

8. **Shield 注册位置**:Shields SHALL register on `on_damage_reduce`
   phase(NOT `on_before_write(hp)`)。详 [`./damage.md`](./damage.md)。

9. **Skill identity**:Skill registration SHALL follow declare-or-get
   pattern;skill index SHALL be globally unique auto-increment;
   `ctx.skill_index` SHALL be sufficient to identify any skill。详
   [`./skill-pattern.md`](./skill-pattern.md)。

10. **Mirror match filter**:Mirror matchup(same char on both sides)
    SHALL load char DSL files per-binding,actor-centric hooks SHALL filter
    events to the loading owner(via `ctx.actor_player` / `ctx.actor_char`)。
    详 [`./skill-pattern.md`](./skill-pattern.md)。

11. **DSL Lua subset**:DSL syntax SHALL be the Lua subset documented in
    [`./builtin-api.md`](./builtin-api.md)。Forbidden 构造包括但不限于
    `for` / `while` / `pairs` / `setmetatable` / `string.*` / 全局变量写入。

12. **Builtin 注册要求**:Builtin APIs SHALL be registered via
    `RegisterBuiltins` in `gicg_engine/interp/`;tokenize 认 ≠ eval 认,
    新 builtin SHALL 在两侧同时注册(详 [`./builtin-api.md`](./builtin-api.md) §2)。
    详 [`./builtin-api.md`](./builtin-api.md)。

13. **Declare-or-get positional**:Files SHALL declare game data via
    positional declare-or-get pattern(`create_counter` / `declare_skill` /
    `declare_card` 等)。详 [`./counter.md`](./counter.md) +
    [`./skill-pattern.md`](./skill-pattern.md)。

14. **Ref 类型契约**:DSL callbacks SHALL NOT use `.id` integer fields —
    always use ref handles(`*SkillRef` / `*CardRef` /
    `LazySkillRef` 等)。Counter metadata 中存 ref 用 `ref_kind` 元数据,
    SHALL NOT 暴露 `.id` 字段(详 [`./skill-pattern.md`](./skill-pattern.md) §1.3)。

15. **Hook owner obs gap**:Hooks bound to char-skills 在 RL obs 中 SHALL be
    discoverable — engine SHALL expose `char_skill_refs` slot
    (`IncludeCharSkillRefs` toggle)。实现与契约详
    [`./hook.md`](./hook.md) §6。

## 4. Subtopics

本 capability 由本文件 + 6 个 subtopic 组成。每个 subtopic 专注一组正交
规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。

- [Counter system](./counter.md) — scope 表 / declare-get / groups / tags /
  Player constants / 使用规则(don't / do)
- [Hook dispatch](./hook.md) — `HookType` 枚举 / Priority / 注册顺序 /
  filter 语义 / hook owner obs gap 修复
- [Damage pipeline](./damage.md) — 5-phase flow / `on_damage_reduce`
  shields / reaction / value 与 element 修改约束
- [Skill pattern](./skill-pattern.md) — registration / mirror filter /
  talent shared-load / DSL load caching / ref 语义
- [Builtin API](./builtin-api.md) — Lua subset(allowed / forbidden)+
  builtin function 列表 / 双侧注册要求
- [File structure](./file-structure.md) — `data/pools/<id>/` 目录布局 +
  加载顺序(capi `systemFiles` 固定枚举)+ 文件自包含约定

## 5. Cross-references

**Engine runtime 行为**(待 engine-runtime spec 落地后从本 spec 迁出):
- `Runtime.LoadFilesWithDeps` — 拓扑加载实现在
  `gicg_engine/interp/loader.go`。Scans each file for declare /
  get pattern,builds dependency graph,topological sort。
- `Runtime.ExecFileSandboxed` — file isolation 实现:DSL files 在隔离
  env 内执行,可 READ builtin APIs / enums,写入留 file-local env,
  跨文件共享仅通过 declare / get 协议。
- DSL load caching — `gicg_engine/interp/loader.go` 进程级 AST cache,
  cache never invalidates during a process lifetime(mid-run DSL edits
  **intentionally** not visible)。Eager preload via
  `gicg_env.engine.preload_dsl('data')`。

**Repo layout / data 树**(`data/pools/<pool>/characters/` /
`data/pools/<pool>/cards/` / `data/system/`)详
[`file-structure.md`](./file-structure.md)。

**Data model**:
- Counter + Hook 数据模型概述见 `CLAUDE.md "Core Model"` 段。
- DSL ref 类型(`SkillRef` / `CardRef`)定义在
  `gicg_engine/interp/registry.go`(L131 / L172)。
- HookType 枚举定义在 `gicg_engine/types.go`(L100+,strict ADR-0019 §B.5
  下 8 时机 damage pipeline)。

**Repository cross-references**:
- DSL exemplar: `data/pools/v_legacy/cards/L3/以牙还牙.lua`
- Lua subset and builtin registration: [`builtin-api.md`](./builtin-api.md)
- DSL reference identity: [`skill-pattern.md`](./skill-pattern.md) §1.3
- Hook-owner observation fields: [`hook.md`](./hook.md) §6
- Strict damage ordering: [`damage.md`](./damage.md) §1.1 and
  [`0019-dsl-v6-semantic-engine`](../../changes/archive/0019-dsl-v6-semantic-engine/)

**Sibling capability specs**(后续 task 落地,本 spec 不创建):
- `openspec/specs/engine-runtime/` — Runtime 加载 / 沙箱 / cache 等行为
- `openspec/specs/pool-versioning/` — ADR-0011 卡池版本治理
- `openspec/specs/rl-obs/` — Python 训练侧 observation 张量契约

## 6. Status

- **Created**:2026-05-15(P0-T8,从
  `docs/1_specs/engine/dsl/conventions.md` 289 行抽取)
- **Version**:0(初始落地)
- **Expected revision triggers**:
  - 新 builtin API 加入(SHALL 走 OpenSpec change)
  - 新 HookType 加入(damage pipeline 调整、新生命周期 hook)
  - 新 counter scope 加入(超出当前 5 种)
  - mirror filter 规则变更(若 engine 改 dispatch 模型)
  - ADR-0019 strict 8 时机表外调整(damage pipeline 重排)
