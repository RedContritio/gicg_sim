---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: engine-capi
---

# Engine C API — libgicg / ctypes 接口 / mirror match / draw 元数据

> 本 capability spec 治理 GICG 引擎对外暴露的 C API surface — Go cgo
> `//export` 函数集合(打包为 `gicg_env/libgicg.dylib` / `.dll` / `.so`)
> 与 Python `gicg_env.GicgEnv` ctypes wrapper 接口契约。本 spec 治理
> **physical C API surface**(签名 / 句柄语义 / 字符串生命周期 /
> Python 包装层 anti-gymnasium 决策)、mirror match per-binding loading、
> 卡牌抽取轮次元数据(reward shaping 支撑)。
>
> 本 spec 从 `docs/1_specs/engine/capi_mirror.md`(164 行)抽取规约,
> SHALL 化。单 spec.md(权威源为 `gicg_engine/capi/*.go` 中
> `//export` 标记,见 §1)。
>
> 与 [`engine-runtime`](../engine-runtime/spec.md) 边界:本 spec 治理
> CAPI surface 与 mirror per-binding loader 约定;runtime 内部
> (`LoadFilesWithDeps` / `ExecFileSandboxed`)由 engine-runtime 治理。

## 1. Purpose

GICG C API 需被规约化,否则会出现:

- 句柄类型(整数 vs 不透明指针)被混用 — 本 engine 用 `C.int` 整数句柄,
  Python SHALL NOT 直接探查 Go memory
- 字符串生命周期(`*C.char` 由 `GameFreeString` 释放)被忽略,造成内存
  泄漏
- Mirror match per-binding loading 的 `BySlot` / `ByName` 区分被静默偏离,
  造成 P0 角色 `SkillIDs == []`(ADR-0003 D11 bug)
- `declare_char` 幂等性 + `bind_char` 不改模板的约定被破坏
- `get_char(name)` 槽感知行为(per-binding 上下文 vs 全局上下文)被
  覆盖,导致闭包错绑
- Talent 卡的"全局加载 + lazy proxy 解析"被误改为"per-binding 加载",
  破坏 mirror match(双侧装备同卡)的支持
- `DrawnAtRound` 抽牌轮次元数据被错误填充(应只 `DrawCard` 与 `add_card`
  覆盖,初始牌库 / 回放恢复保持 0)

**Code authoritative**(签名以代码为准):

- C API 导出:`gicg_engine/capi/*.go` 中所有 `//export` 函数
- Python wrapper:`gicg_env/engine.py`(ctypes 解析)、`gicg_env/env.py`
- Mirror per-binding loader:`gicg_engine/capi/capi.go::splitDSLPaths`、
  `gicg_engine/interp/runtime.go::LoadCharFilesPerBinding`
- Lazy proxy:`SelfSlotProxy` / `LazyCharProxy` / `LazySkillRef` 在
  `gicg_engine/interp/`

## 2. Scope

**In scope**:

- C API 句柄约定(`C.int` 整数 / `GameFree` lifecycle)
- 字符串返回 + `GameFreeString` 释放约定
- `//export` 函数分组:游戏生命周期、动作循环、观测张量、奖励事件、
  游戏状态访问器、标签 / 回放辅助、骰子访问器、对手手牌 / 牌库 / 骰
  setter(确定化注入)
- Python wrapper `GicgEnv`:anti-gymnasium 决策 + 主要 API 形态
- Mirror match per-binding loading 协议(`Chars.ByName` 模板 vs
  `Chars.BySlot` 槽条目 + `declare_char` 幂等 + `bind_char` 不改模板 +
  `get_char` 槽感知 + `declare_skill` 槽感知 + skill hook 槽过滤)
- 加载器拆分(角色文件 per-binding / 卡牌全局 / talent 全局 + lazy proxy)
- `DrawnAtRound` 元数据 4 来源约定 + `LastCardRef` / `LastCardDrawnAt`
  生命周期(每步入口清空)

**Out of scope**:

- 引擎数据模型(`Game` / `Counter` / `CharInfo`)— `gicg_engine/game.go`
  canonical 定义,本 spec 只引
- Observation 编码语义(field 含义、shuffle)— 由
  [`network-architecture/obs.md`](../network-architecture/obs.md) 治理
- Action 编码语义(kind / skill_ref / card_ref 三元组)— 由
  [`engine-actions`](../engine-actions/spec.md) 治理
- Runtime 加载 / 沙箱 / 拓扑排序内部 — 由
  [`engine-runtime`](../engine-runtime/spec.md) 治理
- Reward shaping 公式 — Python 侧 `gicg_env/env.py` + `RewardShaping.coefs`
  (engine 只输出 16 维 raw counter)

## 3. Core SHALL invariants

以下 13 条 invariant 是本 capability 的硬约束。任意冲突应作为 OpenSpec
change 提案修订,而非在代码中静默偏离。

### 3.1 C API 表面契约

1. **C API 暴露**:Engine SHALL expose C API via `libgicg.dylib`(macOS)/
   `.dll`(Windows)/ `.so`(Linux),via cgo `//export`。Python 绑定
   SHALL use `ctypes`(`gicg_env/engine.py`)。

2. **句柄类型 = C.int 整数**:Game 句柄 SHALL be `C.int` 整数(非不透明
   指针);生命周期 SHALL 通过 `GameFree` 管理。Python 端 SHALL NOT
   直接探查 Go memory。

3. **字符串返回释放约定**:Engine 返回 `*C.char` 的函数(如
   `GameGetCardNames` / `GameExportReplay` / `GameGetActiveHookLabels` /
   `GameGetActionLabels` 等)SHALL by 调用方通过 `GameFreeString` 释放,
   否则 SHALL leak。

4. **Paradigm-agnostic**:C API SHALL NOT know about PPO / AZ / CFR / DMC —
   它只暴露 game state / action / obs / reward counter,paradigm-specific
   逻辑(reward 系数、policy head、search)在 Python 侧。

5. **签名权威源**:函数签名 SHALL 以 `gicg_engine/capi/*.go` 中
   `//export` 标记为准 — 当 docs 与代码冲突时以代码为准,新增 export
   SHALL 同步更新相关 spec。

### 3.2 函数分组(必须存在)

6. **生命周期函数**:Engine SHALL expose 以下生命周期函数:
   `GameNew` / `GameFree` / `GameClone` / `GameSnapshot` / `GameRestore` /
   `GameSnapshotFree` / `GameReset`。Clone 与 Snapshot/Restore SHALL
   支撑 search 树的复制 / 快照恢复(详
   [`search-ismcts`](../search-ismcts/spec.md))。

   快照与恢复 SHALL 不推进源局或快照的随机流。相同快照和动作输入 SHALL
   产生相同后续状态；`GameSetSimulationSeed` 显式修改私有模拟局的未来随机流。
   复制 SHALL 包含待处理目标、蓄力、区域、装备占用、奖励累计及随机状态。
   执行中的调用栈 SHALL 不被当作可复制的决策边界；等待玩家输入的受管理
   动作 SHALL 支持克隆与恢复，并保留后续结算。

7. **动作循环函数**:Engine SHALL expose 动作循环:`GameStep` /
   `GameStepTarget` / `GameGetLegalActionCount` / `GameGetLegalActions` /
   `GameGetActionRefs`(`kind / hook_idx / char_idx` triple)/
   `GameGetActionLabels` / `GameIsForcedSwitchPending`。

   旧式卡牌目标选择 SHALL 在 `GameStep` 与 `GameStepTarget` 使用同一解析
   路径，不重复出牌或扣费；原动作的费用修正信息 SHALL 保留到效果执行。
   无效目标 SHALL 保持等待状态不变。

8. **观测张量函数**:Engine SHALL expose 观测:`GameGetStaticObsSize` /
   `GameGetDynamicObsSize` / `GameGetStaticObs`(每 episode 一次)/
   `GameGetDynamicObs`(每步,带 perspective)/ `GameGetCounters` /
   `GameGetCounterCount`。Obs schema 由
   [`network-architecture/obs.md`](../network-architecture/obs.md) 治理。

9. **奖励事件函数**:Engine SHALL expose `GameGetRewardEvents`(返回
   raw counter)+ `GameResetReward`(每步清空)。**Engine SHALL NOT
   compute reward 公式** — 系数缩放与 shaping 由 Python 侧
   (`gicg_env/env.py` + `RewardShaping.coefs`)负责。16 个槽:
   `damage_dealt / damage_received / damage_blocked / shield_absorbed /
   heal_done / enemy_heal_done / kills / total_kills / deaths /
   total_deaths / reactions_triggered / reactions_received /
   energy_overflow / ap_wasted / game_over / winner`。

10. **确定化注入函数**:Engine SHALL expose setter API for hidden state
    injection:`GameSetPlayerHand` / `GameSetPlayerDeck` /
    `GameSetPlayerDice`。这些函数 SHALL 是 IS-MCTS 确定化的接入面(详
    [`search-ismcts/determinization.md`](../search-ismcts/determinization.md))。

### 3.3 Python wrapper

11. **anti-gymnasium 决策**:`gicg_env.GicgEnv` SHALL NOT 继承
    `gymnasium.Env` — 观测 + 动作布局需要 GICG 专属元数据(counter sid /
    hook token / action ref / 每槽 hook 嵌入),与 gymnasium 接口不兼容
    是**有意设计**,SHALL NOT 强行包装。批量消费者参见
    `training/paradigms/az/selfplay.py:VectorizedRollout`。

### 3.4 Mirror match per-binding loading

12. **ByName 模板 vs BySlot 槽条目**:Character registry SHALL maintain
    两类条目:

    | 字段 | 模板(ByName) | 按槽(BySlot) |
    |------|---------------|----------------|
    | `Name` / `Element` / `Weapon` | ✓ | 从模板复制 |
    | `PlayerIdx` / `CharIdx` | `-1` | 绑定的 player / char |
    | `HPCounterID` / `EnergyCounterID` / ... | `-1` | `findSelfCounter(p, c)` 提供 |
    | `Skills` map / `SkillIDs` slice | 空(仅模板) | 每次绑定时填充 |

    `declare_char` SHALL be 幂等(重复 declare 同名返回已有模板)。
    `bind_char` SHALL NOT 修改模板 — 它 SHALL 克隆模板元数据到新
    `*CharEntry`、填充按槽 counter ID,并存入 `BySlot`。

13. **加载器拆分 + lazy proxy**:Engine SHALL load DSL files in 3 modes:

    - **角色专属文件**(`data/pools/<pool_id>/characters/<name>/`)SHALL
      via `Runtime.LoadCharFilesPerBinding` per-binding loading — 每个
      绑定独立 `CharEntry` / 按槽 counter / skill hook 注册 / buff 闭包
    - **卡牌**(`data/pools/<pool_id>/cards/`)SHALL via
      `Runtime.LoadFilesWithDeps` 全局加载一次
    - **Talent 卡**(`requires_char` 在 `declare_card`)SHALL be 全局
      加载一次(即便所需角色绑到多槽)。`filterTalentCardsForSlotUniqueness`
      SHALL only drop `k == 0`(没有任何一方装备该角色),`k >= 1`(包括
      mirror `k == 2`)SHALL 一律保留。共享加载的 hook SHALL via
      `SelfSlotProxy` / `LazyCharProxy` / `LazySkillRef` 三组 lazy 代理在
      触发时动态解析所有者。

    `get_char(name)` SHALL be **槽感知**:在 per-binding 上下文
    (`rt.CurrentOwnerPlayer/Char` 已设置)返回 `BySlot[currentOwner]`,
    在槽上下文之外(全局拓扑加载的卡牌)回退到模板。
    `declare_skill` SHALL be 槽感知:技能 ID 全局只注册一次(via 模板),
    技能通过 `g.AddSkill(pi, ci, skillID)` + per-player hook filter 附加
    到当前所有者槽。Hook filter SHALL 早返回
    `ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar`,
    确保按槽注册永不跨槽触发。

### 3.5 抽牌轮次元数据

14. **`DrawnAtRound` 4 路径覆盖**:`CardInst.DrawnAtRound` SHALL be set
    在卡牌进入手牌时,按下表:

    | 路径 | `DrawnAtRound` 取值 |
    |------|---------------------|
    | `BuildDeck`(初始牌库) | `0` |
    | `Game.DrawCard`(牌库 → 手牌) | `g.Round`(覆盖初始 0) |
    | `add_card` 内置(DSL 注入,如复刻) | `g.Round` |
    | `record/load.go`(回放恢复) | `0`(回放不计算奖励加成) |

    `Game.LastCardRef` 与 `Game.LastCardDrawnAt` SHALL be set by
    `executeCard`,并 SHALL be 在**每次 `Step` 入口处清空** — 奖励塑形
    SHALL only fire 在实际 ActionCard 步骤(而非下一步)。
    该字段用于 `gicg_env/env.py` 计算新颖卡牌奖励加成
    (`training/paradigms/az/config.py::RewardShaping.novel_cards`)。

## 4. Cross-references

**Sibling capability specs**:

- [`openspec/specs/engine-actions/`](../engine-actions/spec.md) — 动作
  枚举语义(本 spec 暴露 `GameGetLegalActions` / `GameGetActionRefs` /
  `GameStep`,actions spec 治理这些函数语义)
- [`openspec/specs/engine-dice/`](../engine-dice/spec.md) — 骰子机制
  (本 spec 暴露 `GameSetPlayerDice` / `GameGetDicePaid` / 等等)
- [`openspec/specs/engine-runtime/`](../engine-runtime/spec.md) — DSL
  加载内部(本 spec 治理 mirror per-binding 协议,runtime 治理
  `LoadFilesWithDeps` / `ExecFileSandboxed` 算法)
- [`openspec/specs/engine-dsl/`](../engine-dsl/spec.md) — DSL declare /
  get 协议(本 spec 治理 `declare_char` / `bind_char` 幂等性 + 槽感知)
- [`openspec/specs/network-architecture/obs.md`](../network-architecture/obs.md) —
  obs 字段语义(本 spec 只 export `GameGetStaticObs` / `GameGetDynamicObs`
  接口,obs 内部布局在 network)
- [`openspec/specs/search-ismcts/`](../search-ismcts/spec.md) — Snapshot
  / Restore / Clone + 确定化注入 setter 的消费者
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) — 格式
  与阈值

**Architecture decisions**:

- ADR-0003 D11 mirror match per-binding loading bug + fix(commit
  `634f2ed` talent B 方案)— 详
  [`docs/2_decisions/adr-0003-engine_bugs_d10_d13.md`](../../../docs/2_decisions/adr-0003-engine_bugs_d10_d13.md)
- ADR-0011 pool versioning(`data/pools/<pool_id>/` 加载分区)— 详
  [`docs/2_decisions/adr-0011-pool_versioning.md`](../../../docs/2_decisions/adr-0011-pool_versioning.md)

**History / postmortems**:

- `docs/1_specs/engine/capi_mirror.md` (deleted, migrated here) —
  本 spec 的 narrative source,已加 deprecation note,保留至 P1++
  整体清理

## 5. Status

- **Created**:2026-05-15(P1-T4)
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/engine/capi_mirror.md`(164 行)
- **Known drift**:`docs/1_specs/engine/capi_mirror.md` 列举的 export
  集合比 `gicg_engine/capi/*.go` 当前实际 export 少(主要是骰子相关
  setter / getter 与 typed obs constants)— 本 spec 用"分组必须存在"
  SHALL 而非穷举枚举,实际签名以代码为准
- **Expected revision triggers**:
  - 新 export 加入(骰子真实化 / typed obs 扩展 / replay 元数据扩展)
  - 句柄类型放开到指针 / 改 ABI(本 spec 明确 SHALL `C.int` 整数)
  - Mirror per-binding 协议变更(若 `bind_char` 改动 / lazy proxy 路径
    重排 / 角色文件加载模式变更)
  - `DrawnAtRound` 来源扩充(若新增"copy card to hand"类路径)
  - GicgEnv 决定继承 gymnasium(本 spec 明确 SHALL NOT)
