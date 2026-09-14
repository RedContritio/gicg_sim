---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: engine-runtime
---

# Engine Runtime — DSL 加载 / 拓扑排序 / 沙箱执行 / 进程级 AST cache

> 本 capability spec 治理 `gicg_engine/interp/` Runtime 的 DSL 文件加载
> 行为:基于 declare / get 关系扫描 + 拓扑排序的依赖图加载
> (`Runtime.LoadFilesWithDeps`)、文件隔离执行环境
> (`Runtime.ExecFileSandboxed`)、进程级 AST cache(`loader.go`)、
> 跨文件共享只许 declare / get 协议的不变量。
>
> 本 spec 从 `docs/1_specs/engine/dsl/conventions.md` L83-95
> "Dependency Graph" + "File Isolation" 段(~13 行)+
> `engine-dsl/spec.md` §5 cross-reference 中已 documented 的 runtime 行为
> 抽取规约,SHALL 化 + 扩展(基于 `gicg_engine/interp/` 实际行为)。
> 单 spec.md(权威源为代码,见 §1 引用)。
>
> 与 [`engine-dsl`](../engine-dsl/spec.md) 边界:本 spec 治理 runtime
> 加载机制(loader 算法 / 沙箱语义 / cache 行为);DSL 作者面向约定
> (declare-or-get 写法 / hook 写法 / mirror filter)由 engine-dsl 治理。
> 与 [`engine-capi`](../engine-capi/spec.md) 边界:本 spec 治理 runtime
> 内部;mirror per-binding `LoadCharFilesPerBinding` 协议(`Chars.ByName` /
> `Chars.BySlot` 双轨表 + lazy proxy)由 engine-capi 治理。

## 1. Purpose

GICG runtime 加载需被规约化,否则会出现:

- DSL 文件加载顺序不被依赖图保证(declare provider 后于 consumer 加载)
  造成 `get_counter` / `get_skill` / `get_char` 找不到目标,引擎 panic
- 文件全局变量泄漏:某文件 `local X = ...` 漏 `local` 后污染另一文件
- 跨文件共享走 file-global / Go global 等非 declare / get 协议路径,造成
  refactor 漂移
- AST cache 行为被破坏(mid-run 重读文件 / 跨进程 stale cache)
- `RegisterBuiltins` 在 tokenize 但未 eval 注册造成 builtin 看似可用实则
  fail(详 [`engine-dsl/builtin-api.md`](../engine-dsl/builtin-api.md) §2)
- mirror match 角色文件每绑定执行两次时,non-Self 作用域 counter 被
  重复 declare 而 engine 未实现幂等行为

**Code authoritative**(行为以代码为准):

- 拓扑加载:`gicg_engine/interp/runtime.go::LoadFilesWithDeps`
- 沙箱执行:`gicg_engine/interp/runtime.go::ExecFileSandboxed`
- AST cache:`gicg_engine/interp/loader.go`
- Builtin 注册:`gicg_engine/interp/builtins.go::RegisterBuiltins`
- Mirror per-binding loader:`gicg_engine/interp/runtime.go::LoadCharFilesPerBinding`
  (协议本身由 [`engine-capi`](../engine-capi/spec.md) 治理)
- Eager preload:`gicg_env/engine.py::preload_dsl`

## 2. Scope

**In scope**:

- DSL 文件依赖图扫描(declare provider / get consumer 识别)
- 拓扑排序与加载顺序(`LoadFilesWithDeps`)
- 沙箱执行环境(`ExecFileSandboxed`)读写边界
- 进程级 AST cache 语义(parse 一次 / cache 永不失效 / mid-run 不见编辑)
- Eager preload 入口(`preload_dsl`)
- Builtin 双侧注册要求(tokenize + eval 一致)
- 跨文件共享唯一协议(declare / get 系列 builtin)
- Per-binding 加载下 counter declare 的幂等约定
- mirror loader 与 talent shared-load 行为概述(协议细节在 engine-capi)

**Out of scope**:

- DSL 作者面向 API(`declare_counter` / `get_counter` / `declare_skill` /
  `get_skill` / `get_char` / hook 注册函数)— 由
  [`engine-dsl`](../engine-dsl/spec.md) 治理
- DSL Lua subset(allowed / forbidden 构造)— 由
  [`engine-dsl/builtin-api.md`](../engine-dsl/builtin-api.md) 治理
- Mirror match per-binding loading 协议(`Chars.ByName` / `BySlot` /
  lazy proxy)— 由 [`engine-capi`](../engine-capi/spec.md) 治理
- Pool 选择(`GameConfig.Pools` / 加载分区)— ADR-0011 + 后续
  `pool-versioning` spec 治理
- C API 表面(`GameNew` 调用入口)— 由
  [`engine-capi`](../engine-capi/spec.md) 治理

## 3. Core SHALL invariants

以下 9 条 invariant 是本 capability 的硬约束。任意冲突应作为 OpenSpec
change 提案修订,而非在代码中静默偏离。

### 3.1 依赖图加载

1. **依赖图扫描**:`Runtime.LoadFilesWithDeps(paths)` SHALL scan each
   file for declare / get builtins:
   - `declare_counter` / `declare_char` / `declare_skill` /
     `declare_card` SHALL be 视为 provides(provider 标记)
   - `get_counter` / `get_char` / `get_skill` SHALL be 视为 depends
     (consumer 标记)
   - 扫描 SHALL be 静态(基于 AST / token),SHALL NOT 依赖 runtime
     evaluation 副作用

2. **拓扑排序加载**:Loader SHALL 构建依赖图后做拓扑排序,SHALL 在
   排序顺序下逐文件加载。Provider 文件 SHALL 早于 consumer 文件加载。
   循环依赖 SHALL panic(loader 不能保证收敛,作者必须解开循环)。

3. **静态扫描架构约束**:由于扫描静态进行,char-skill 文件 SHALL NOT
   通过 `get_card("X")` 反向依赖 card 文件 — 该 pattern 在拓扑排序时
   不可见。反向用 sharedFiles 引用 char 是允许的反向 pattern。
   (详 [`engine-dsl/file-structure.md`](../engine-dsl/file-structure.md) §8)

### 3.2 沙箱执行

4. **文件隔离执行**:Each file SHALL execute via
   `Runtime.ExecFileSandboxed` in an isolated environment:
   - 文件 SHALL be able to READ builtin APIs / enums(via
     `RegisterBuiltins`)
   - 文件级写入(`local x = ...`)SHALL stay file-local — SHALL NOT
     泄漏到其他文件或 Go global
   - 全局变量写入(`x = ...` without `local`)SHALL be forbidden by
     DSL Lua subset(见 [`engine-dsl/builtin-api.md`](../engine-dsl/builtin-api.md))

5. **跨文件共享唯一协议**:Cross-file data sharing SHALL ONLY occur via
   declare / get pattern:`declare_counter` / `get_counter`、
   `declare_skill` / `get_skill`、`declare_char` / `get_char` /
   `bind_char`。SHALL NOT use 任何 file-global / Go-global / 文件路径
   import 类机制。

### 3.3 AST cache 与 preload

6. **进程级 AST cache**:`gicg_engine/interp/loader.go` SHALL parse each
   `.lua` file under configured `data_dir` 一次 per process,并 SHALL
   cache AST。Cache SHALL NOT invalidate during process lifetime —
   mid-run DSL edits SHALL NOT be visible(此为有意决策,保证 RL
   训练运行期 game-rule 不漂移)。

7. **Eager preload 入口**:Python 侧 SHALL be able to eager-preload all
   DSL via `gicg_env.engine.preload_dsl(data_dir)` — 避免每次 `GameNew`
   时 lazy parse 拖慢首次加载。

### 3.4 Builtin 注册

8. **双侧注册要求**:Builtin APIs SHALL be registered at BOTH tokenize
   side(parser 知道 token)AND eval side(runtime 知道 callable)。
   仅 tokenize 注册而未 eval 注册 SHALL 在调用时 panic /
   undefined-symbol。新 builtin 加入 SHALL via `RegisterBuiltins` 在
   两侧同时注册。Counter 参数 SHALL use 类型断言而非位置 idx 推断。
   (详 [`engine-dsl/builtin-api.md`](../engine-dsl/builtin-api.md) §2)

### 3.5 Per-binding 加载下的 counter 幂等

9. **Counter declare 幂等约定**:在角色专属文件 per-binding 加载
   (`LoadCharFilesPerBinding`)上下文中,同一 DSL 文件以不同所有者
   上下文被 `ExecFileSandboxed` 执行两次。对**非 Self / 非 ActiveStatus
   作用域**的 counter,`declare_counter` SHALL be idempotent — 第二次
   加载 SHALL NOT 重复创建 counter。`Self` / `ActiveStatus` 作用域
   counter 的键 SHALL 包含 owner char 名(通过
   `CurrentFileCharOwner` / `CurrentFileTalentOwner` 注入 scope key),
   保证每绑定独立。

## 4. Cross-references

**Sibling capability specs**:

- [`openspec/specs/engine-dsl/`](../engine-dsl/spec.md) — DSL 作者面向
  约定 + builtin API + Lua subset(本 spec 治理加载机制,engine-dsl
  治理 DSL 写法)
- [`openspec/specs/engine-capi/`](../engine-capi/spec.md) — Mirror match
  per-binding loading 协议(`Chars.ByName` / `BySlot` 双轨表 + lazy
  proxy)与 C API 加载入口(`GameNew`)
- [`openspec/specs/engine-actions/`](../engine-actions/spec.md) — 系统
  规则 DSL 文件清单(`data/system/*.lua` 由本 spec 的 runtime 加载)
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) — 格式
  与阈值

**Repository references**:

- declare/get 静态扫描约束见
  [`engine-dsl/file-structure.md`](../engine-dsl/file-structure.md) §8。
- Builtin 双侧注册要求见
  [`engine-dsl/builtin-api.md`](../engine-dsl/builtin-api.md) §2。
- Bridge globals 的实际注册与读取位置以
  `gicg_engine/interp/runtime.go` 和 `builtins.go` 为准。

**History / source**:

- `docs/1_specs/engine/dsl/conventions.md` (deleted, migrated here) —
  L83-95 "Dependency Graph" + "File Isolation" 段,本 spec 的 narrative
  source 之一(已加 P1-T4 inline moved note)
- `docs/1_specs/engine/capi_mirror.md` (deleted, migrated here) —
  加载器拆分(角色文件 per-binding / 卡牌全局 / talent shared)narrative
  source(已加 P1-T4 deprecation note,协议由 engine-capi 治理)

## 5. Status

- **Created**:2026-05-15(P1-T4)
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/engine/dsl/conventions.md` L83-95 + 扩展自
  `gicg_engine/interp/` 已 documented 行为(无新加 invariant,只 SHALL
  化已 shipped 契约)
- **Expected revision triggers**:
  - 依赖图扫描扩展(若新 declare / get 系列加入)
  - 沙箱模型变更(若放开 file-global 写 / 跨文件 import)
  - AST cache 失效策略放开(若 mid-run reload 加入,此为 RL 训练稳定性
    破坏,需 OpenSpec change)
  - 循环依赖处理变更(若加入 lazy declare / forward declare)
  - Builtin 注册路径变更(若两侧合并到单一注册点)
