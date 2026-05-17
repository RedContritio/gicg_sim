# 引擎设计 — Go-Python 接口 / Mirror match / Card draw 元数据

> **MOVED to `openspec/specs/engine-capi/`**（2026-05-15，P1-T4）
>
> 本文档内容已迁到 OpenSpec（SHALL 语言）。
> 新 spec:[engine-capi/spec.md](../../../openspec/specs/engine-capi/spec.md)
> 本文件保留至 P1++（`docs/1_specs/` 整体清理）；**只读**。

---

> 本文是 `README.md` 的延续。前置阅读：`README.md` 第 1-4 节和 `actions.md`。

## 9. Go-Python 接口

### 9.1 C API（cgo 导出）

规范信息源是 `gicg_engine/capi/capi.go`——每当新增导出时请同步更新此文档。
所有句柄均为 `C.int` 整数（非不透明指针）；生命周期通过 `GameFree` 管理。

**游戏生命周期：**

```go
//export GameNew            // (configJSON *C.char) C.int — 返回游戏句柄
//export GameFree           // (id C.int)
//export GameClone          // (id C.int) C.int — 返回克隆句柄
//export GameSnapshot       // (id C.int) C.int — 返回快照 id
//export GameRestore        // (id C.int, snapID C.int) C.int
//export GameSnapshotFree   // (snapID C.int)
//export GameReset          // (id C.int, seed C.long)
```

**动作循环：**

```go
//export GameStep                   // (id C.int, actionIdx C.int) C.int
//export GameStepTarget             // (id C.int, targetIdx C.int) C.int
//export GameGetLegalActionCount    // (id C.int) C.int
//export GameGetLegalActions        // (id C.int, outKinds *C.int, outIndices *C.int)
//export GameGetActionRefs          // (id C.int, out *C.int) — 3*N 个 int：每个动作 [kind, hook_idx, char_idx]
//export GameGetActionLabels        // (id C.int) *C.char — 换行符分隔的 "Kind\tName"
//export GameIsForcedSwitchPending  // (id C.int) C.int — 1 表示等待强制换人
```

**观测张量**（见 `gicg_engine/observation.go`）：

```go
//export GameGetStaticObsSize   // () C.int
//export GameGetDynamicObsSize  // () C.int
//export GameGetStaticObs       // (id C.int, out *C.int)     — 每个 episode 调用一次
//export GameGetDynamicObs      // (id C.int, perspective C.int, out *C.int) — 每步调用
//export GameGetCounters        // (id C.int, outValues *C.int, count C.int)
//export GameGetCounterCount    // (id C.int) C.int
```

**奖励事件（原始 counter，Python 端进行缩放）：**

```go
//export GameGetRewardEvents  // (id C.int, player C.int, out *C.int) — 16 个 int32
//export GameResetReward      // (id C.int, player C.int) — 清空每步 counter
```

16 个槽分别是：`damage_dealt, damage_received, damage_blocked, shield_absorbed, heal_done, enemy_heal_done, kills, total_kills, deaths, total_deaths, reactions_triggered, reactions_received, energy_overflow, ap_wasted, game_over, winner`。Python 端（`gicg_env/env.py`）将每项乘以 `RewardShaping.coefs` 中的系数。引擎不内置任何固定的奖励公式。

**游戏状态访问器：**

```go
//export GameGetPhase           // (id C.int) C.int
//export GameGetTurn            // (id C.int) C.int
//export GameGetWinner          // (id C.int) C.int  — -1 进行中，0=P0，1=P1，2=平局
//export GameGetActiveChar      // (id C.int, player C.int) C.int
//export GameGetHandCount       // (id C.int, player C.int) C.int
//export GameGetDeckCount       // (id C.int, player C.int) C.int
//export GameGetCurrentRound    // (id C.int) C.int
//export GameGetLastCardRef     // (id C.int) C.int  — -1 表示上一步不是打牌
//export GameGetLastCardDrawnAt // (id C.int) C.int
```

**标签 / 回放辅助函数**（返回 `*C.char`，调用方通过 `GameFreeString` 释放）：

```go
//export GameGetCardNames              // (id C.int) *C.char — "ref\tname\nref\tname\n..."
//export GameExportReplay              // (id C.int) *C.char — YAML 回放
//export GameGetActiveHookLabels       // (id C.int) *C.char
//export GameGetActiveCounterSlotLabels // (id C.int) *C.char
//export GameFreeString                // (s *C.char)
```

### 9.2 Python env 包装层

实际消费者是 `gicg_env.GicgEnv`（非 gymnasium 子类）。
它加载 `gicg_env/libgicg.dylib`，通过 `ctypes` 解析上述所有 C API，
并暴露一个轻量的 Python 外观：

```python
from gicg_env import GicgEnv

env = GicgEnv(
    team_0=["赤蝶"], team_1=["墨客"],
    data_dir="data",
    card_pool=None,              # None = 所有卡牌
    reward_coefs=None,            # None = RewardCoefs 中的默认系数
)
obs = env.reset(seed=42)
kinds, indices = env.get_legal_actions()
refs = env.get_action_refs()     # (n_legal, 3) int32
obs, reward, done, info = env.step(action_idx)
```

Env 的构造**有意**不兼容 gymnasium——观测 + 动作布局需要 GICG 专属元数据
（counter sid、hook token、action ref、每槽 hook 嵌入）。
批量消费者请参见 `training/az/selfplay.py:VectorizedRollout`。

## 10. Mirror match 按绑定加载角色文件

角色注册表区分**模板条目**（`Chars.ByName[name]` 中）和**按槽条目**（`Chars.BySlot[p][c]` 中）。

| 字段 | 模板（ByName） | 按槽（BySlot） |
|-------|-------------------|-------------------|
| `Name`, `Element`, `Weapon` | ✓ | 从模板复制 |
| `PlayerIdx`, `CharIdx` | -1 | 绑定的 player/char |
| `HPCounterID`, `EnergyCounterID`, ... | -1 | 来自 `findSelfCounter(p, c)` |
| `Skills` map, `SkillIDs` slice | 空（仅模板元数据） | 每次绑定时填充 |

`declare_char` 是**幂等的**：重复声明同名角色会返回已有模板。`bind_char` **不会**修改模板——它将模板元数据克隆到全新的 `*CharEntry` 中，填充按槽 counter ID，并存入 `BySlot`。

`get_char(name)` 是**槽感知的**：在按绑定加载上下文中（`rt.CurrentOwnerPlayer/Char` 已设置），它返回 `BySlot[currentOwner]` 而非模板。这意味着在按绑定加载期间捕获的闭包（例如赤蝶_蝶火.lua 中的 `local 赤蝶 = get_char("赤蝶")`）引用的是正确的按槽条目。在槽上下文之外（通过全局拓扑加载器加载的卡牌），`get_char` 回退到模板。

`declare_skill` 同样是槽感知的：全局技能 ID 只注册一次（通过模板），但技能通过 `g.AddSkill(pi, ci, skillID)` 和按玩家过滤的 hook 附加到**当前所有者上下文的槽**。Hook 过滤条件为：

```go
if ctx.ActorPlayer != slotPlayer || ctx.ActorChar != slotChar {
    return
}
```

因此按槽注册永远不会跨槽触发。

### 加载器拆分

角色专属文件位于 `data/pools/<pool_id>/characters/<name>/` 下，通过 `Runtime.LoadCharFilesPerBinding` **每次绑定加载一次**。卡牌位于 `data/pools/<pool_id>/cards/` 下，通过 `Runtime.LoadFilesWithDeps` 全局加载一次。`helpers_test.go::splitDSLPaths` 和 `capi.go::splitDSLPaths` 都按此约定对收集到的 DSL 路径进行分区。pool 选择由 `GameConfig.Pools` 决定，默认 `["v_legacy"]`（详见 ADR-0011）。

**天赋牌（B 方案，commit 634f2ed）：** `data/pools/v_legacy/cards/L5/` 下含 `requires_char` 的天赋牌**全局加载一次**，即便所需角色被绑定到多个槽也会保留。`filterTalentCardsForSlotUniqueness` 仅丢弃 `k == 0`（没有任何一方装备该角色）的天赋，`k ≥ 1`（包括镜像的 `k == 2`）一律保留。共享加载的 hook 通过三组 lazy 代理在触发时动态解析所有者：

- `SelfSlotProxy`：`Scope.Self`/`ActiveStatus` counter 在共享加载上下文中返回此代理；`:get()/:set(v)` 时经 `(CurrentContextPlayer, find_slot(player, OwnerName))` 解析到当前 actor 的 slot。
- `LazyCharProxy`：`get_char(name)` 在共享加载上下文返回此代理；`:owner_player()/:owner_char()` 等访问时解析到 `find_slot(CurrentContextPlayer, name)`。
- `LazySkillRef`：`get_skill(char, name)` 和 `invoke_skill(ref)` 在共享加载上下文通过此延迟到触发时解析到 per-binding 的 `SkillRef`。

写入 `Self`/`ActiveStatus` counter 的 hook 看到的 `CurrentContextPlayer/OwnerChar` 等于 counter 所有者（不是 `ctx.ActorPlayer`），所以例如猫爪护盾的 `on_after_write(Sub)` 读到的是护盾主的 `active:get()` 而非攻击者的。

按绑定加载的保证（非 talent）：
- 每个角色绑定（P0:c0:赤蝶 与 P1:c0:赤蝶）各自拥有独立的 `CharEntry`、独立的按槽 counter、独立的技能 hook 注册以及独立的 buff hook 闭包。
- 同一 DSL 文件以不同所有者上下文被 `ExecFileSandboxed` 执行两次；对于非 Self 作用域，`declare_counter` 已是幂等的（Self 的键包含所有者 char 名，通过 `CurrentFileCharOwner`/`CurrentFileTalentOwner` 注入 scope key），因此第二次加载不会重复创建 counter。

### 为何这很重要

在此修复之前，镜像对战（赤蝶 vs 赤蝶）存在结构性缺陷：`declare_char` 覆盖 `ByName` 导致 P0 的条目成为孤儿，全局加载的技能文件只将技能附加到 `ByName[赤蝶]` 碰巧指向的条目——也就是 P1 的条目，因为 P1 最后绑定。P0 的角色最终 `SkillIDs == []`，`GetLegalActions()` 只返回 `EndTurn`。完整的 bug 事后分析见 `../../2_decisions/adr-0003-engine_bugs_d10_d13.md` D11。

## 11. 抽牌轮次追踪（奖励塑形支持）

`CardInst` 携带一个 `DrawnAtRound int` 字段，在卡牌进入玩家手牌时更新：

| 路径 | 创建时的 DrawnAtRound |
|------|------------------------------|
| `BuildDeck`（初始牌库） | `0` |
| `Game.DrawCard`（牌库 → 手牌） | `g.Round`（覆盖初始的 0） |
| `add_card` 内置函数（DSL 注入，如复刻） | `g.Round` |
| `record/load.go`（回放恢复） | `0`（回放不计算奖励加成） |

`Game.LastCardRef` 和 `Game.LastCardDrawnAt` 由 `executeCard` 设置，并在**每次 `Step` 入口处清空**，因此奖励塑形只在实际的 ActionCard 步骤触发（而非下一步）。

用于 `gicg_env/env.py` 中计算新颖卡牌奖励加成
（`training/az/config.py` 中的 `RewardShaping.novel_cards`）。
