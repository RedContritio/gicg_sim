---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: engine-actions
---

# Engine Actions — 动作枚举 / HookActionCheck 过滤 / 执行管道

> 本 capability spec 治理 GICG 引擎的动作系统(action enumeration、
> HookActionCheck 过滤、执行管道、回合框架、系统规则 DSL、Filter 机制)。
> 引擎只做**结构化枚举**(active char skills / hand cards / 切换 / 结束回合),
> 所有条件判断(AP / 能量 / 冻结 / 饱腹 / 卡牌专属条件)由 DSL 通过
> `HookActionCheck` 实现。回合阶段推进与系统规则(round.lua / energy.lua /
> draw.lua / timeout.lua 等)同样以 DSL 形式驻在 `data/system/`,引擎只触发
> 对应 hook。
>
> 本 spec 从 `docs/1_specs/engine/actions.md`(122 行)抽取规约,SHALL 化。
> 单 spec.md,无 subtopic。
>
> 与 [`engine-dsl`](../engine-dsl/spec.md) 的边界:本 spec 治理动作流水中
> **engine 侧职责**与触发的 hook 名;hook 内部 DSL 写法(filter 早返回 /
> declare-or-get / mirror filter)由 engine-dsl 治理。

## 1. Purpose

GICG 引擎动作系统需被规约化,否则会出现:

- 引擎在 `GetLegalActions` 中**条件判断**(AP/能量/冻结)代替 DSL hook 过滤,
  破坏 "engine ignorant of game mechanics" 契约(`CLAUDE.md "Engine Ignorance"`)
- `HookActionCheck` 默认值 / `ctx.playable` 语义被静默偏离(默认 true /
  hook 可置 false)
- 动作执行管道的 hook 顺序(`HookActionPrepare` → 扣费 → `HookSkillUse` /
  `HookCardPlay` / `HookSwitch` → `HookBeforeTurnFlip`)在 refactor 中被打乱
- 强制切换(死亡 / 超载)通过 `defer` 队列进入,**不消耗 AP 且不翻转
  行动权**这一不变量被破坏
- 系统规则 DSL(`data/system/`)被错误下放到 Go,造成 engine 与 DSL 边界
  漏失
- Filter 字段语义(`SELF` 角色级 vs `ACTIVE` 槽位级 / `action_context` /
  `source` / `require_hit`)被误用

本 spec 提供 5 大类约束:

- **Action enumeration**(§3.1-3.2)— 候选枚举 + HookActionCheck 过滤
- **Action execution**(§3.3-3.4)— 执行管道 + 强制切换
- **Round phases**(§3.5)— 回合框架与 hook 顺序
- **System DSL**(§3.6)— 系统规则在 DSL 中实现
- **Filter semantics**(§3.7)— hook filter 字段语义

## 2. Scope

**In scope**:

- 动作候选枚举规则(`GetLegalActions`)— 结构化枚举,无条件判断
- `HookActionCheck` 协议(ctx.playable 语义 / 候选 ctx 字段)
- 动作执行管道(prepare → 扣费 → kind-specific hook → turn flip)
- 强制切换(`FORCED_DEATH` / `FORCED_REACTION`)— 通过 defer 队列、
  不消耗 AP、不翻转行动权
- 回合阶段推进(`NewRound` / `EndPhase`)+ HookRoundStart / HookRoundEnd*
- 系统规则 DSL 清单(`data/system/*.lua` 7 文件职责表)
- Filter 字段语义(`SELF` / `ACTIVE` / `source` / `action_context` /
  `skill` / `skill_mask` / `card_ref` / `require_hit`)

**Out of scope**:

- Hook 内部 DSL 写法(filter 早返回 / declare-or-get / mirror filter)—
  由 [`engine-dsl`](../engine-dsl/spec.md) 治理
- 骰子支付(`action_payments`)— 由 [`engine-dice`](../engine-dice/spec.md)
  治理
- C API 暴露(`GameStep` / `GameGetLegalActions` / `GameGetActionRefs`)—
  由 [`engine-capi`](../engine-capi/spec.md) 治理
- DSL 加载顺序与隔离 — 由 [`engine-runtime`](../engine-runtime/spec.md) 治理
- RL 训练侧 obs / action 编码 — 由
  [`network-architecture`](../network-architecture/spec.md) 治理

## 3. Core SHALL invariants

以下 13 条 invariant 是本 capability 的硬约束。任意冲突应作为 OpenSpec
change 提案修订,而非在代码中静默偏离。

### 3.1 动作候选枚举

1. **结构化枚举**:`Game.GetLegalActions` SHALL only perform structural
   enumeration over `(active char's skills 0..N-1, hand cards, alive
   non-active chars for switch, EndTurn)` — SHALL NOT 内含任何 game-mechanic
   条件判断(AP / 能量 / 冻结 / 饱腹 / 卡牌专属)。

2. **EndTurn 始终可用**:`EndTurn` SHALL be enumerated in every legal-action
   query(无 hook 过滤可隐藏 EndTurn)。

### 3.2 HookActionCheck 过滤

3. **HookActionCheck 协议**:每个候选 SHALL fire `HookActionCheck` with
   ctx fields `(playable, kind, skill_index, card_ref, ...)`,`ctx.playable`
   SHALL default to `true`,hook callbacks SHALL set `ctx.playable = false`
   to reject。仅 `ctx.playable == true` 的候选 SHALL enter legal action list。

4. **过滤由 DSL 实现**:All game-mechanic action filtering SHALL be
   implemented in DSL via `HookActionCheck` — AP(`system/round.lua`)/
   能量(`declare_skill` 注册)/ 冻结(`system/frozen.lua`)/ 饱腹
   (`system/food.lua`)/ 卡牌专属(各卡牌 `on_action_check`)。

### 3.3 动作执行管道

5. **执行管道顺序**:Action 执行 SHALL run hooks in fixed order:
   `HookActionPrepare` → DSL 扣费(via prepare hooks or skill hooks)→
   kind-specific hook(`HookSkillUse` / `HookCardPlay` / `HookSwitch`,
   按 filter 匹配)→ `HookBeforeTurnFlip`。`pushEvent` 在 prepare 前,
   `popEvent` 在 kind-specific hook 后。

6. **ActionPrepare ctx 字段**:`HookActionPrepare` ctx SHALL include
   `(ap_cost, energy_cost, battle_action, ...)` 可被 DSL hook 修改(减费、
   快速行动翻转),engine SHALL read final ctx values after all hooks fire。

7. **Turn flip 由 battle_action 决定**:`HookBeforeTurnFlip` ctx 可被
   hook 修改;`ctx.battle_action == true` SHALL trigger 翻转行动权,
   否则 SHALL NOT 翻转。

### 3.4 强制切换

8. **强制切换不消耗 AP / 不翻转行动权**:Forced switches caused by death
   或 overload reaction SHALL enter via defer queue with
   `action_context = FORCED_DEATH | FORCED_REACTION`,SHALL NOT 消耗 AP
   且 SHALL NOT 翻转行动权。需要玩家选择目标时 SHALL 暂停管道返回等待
   输入。

### 3.5 回合框架

9. **NewRound / EndPhase hook 顺序**:回合推进 SHALL fire hooks in fixed
   order:

   ```
   NewRound:
     Round++
     HookRoundStart (round.lua AP重置 / energy.lua 能量分配 / counter 重置)
     Phase = Action

   EndPhase:
     Phase = RoundEnd
     HookRoundEnd               状态结算(先手方 → 后手方)
     HookRoundEndPostSummon     召唤物结算
     HookRoundEndDecay          持续时间衰减
     HookRoundEndFinal          draw.lua 抽牌 / timeout.lua 判负
     if !GameOver → NewRound
   ```

   引擎 SHALL NOT 内含任何 AP / 能量 / 抽牌 / 判负公式 — 全部由 DSL
   在对应 hook 中实现。

### 3.6 系统规则 DSL

10. **系统规则 by DSL**:以下规则 SHALL be implemented in DSL under
    `data/system/` and SHALL NOT 硬编码进 engine:

    | 文件 | 职责 | 使用的引擎机制 |
    |------|------|---------------|
    | `round.lua` | AP counter 创建 + HookRoundStart 重置 + 先手判定 | counter + HookRoundStart + HookActionCheck |
    | `death.lua` | on_after_write(hp, SUB) HP≤0 → set_alive(false) + defer 强制切换 | counter + on_after_write + defer + set_alive |
    | `energy.lua` | HookRoundStart 分配 + HookAfterDamage(require_hit) 技能能量 | counter + HookActionCheck |
    | `frozen.lua` | HookActionCheck 冻结 counter → 阻止技能 / 切换 | counter + HookActionCheck |
    | `draw.lua` | HookRoundEndFinal 双方各抽 2 张;开局抽 5 张 | `draw_card()` |
    | `timeout.lua` | HookRoundStart(round==1) 记录先手 counter + HookRoundEndFinal 判负 | counter + set_winner |
    | `food.lua` | 食物 → 饱腹 counter + HookActionCheck 阻止再次使用 | counter + HookActionCheck |

### 3.7 Filter 机制

11. **Actor filter**:Hook filter SHALL distinguish `SELF`
    (`hook.OwnerChar == ctx.ActorChar`,角色级匹配)与 `ACTIVE`
    (`Players[hook.OwnerPlayer].ActiveChar == ctx.ActorChar`,槽位级匹配)。
    `active_status` scope counter 的 hook SHALL pair with `ACTIVE` filter,
    确保只匹配当前出战角色的行动;后台角色被 `invoke_skill` 触发时不匹配。

12. **其他 filter 字段语义**:Hook filter SHALL support 字段及默认值:

    | 字段 | 默认 | 含义 |
    |------|------|------|
    | `source` | any | 匹配 `ctx.source`(SKILL / CARD / STATUS / SUMMON / SUPPORT / REACTION) |
    | `action_context` | any | 匹配 `ctx.action_context`(USE_SKILL / PLAY_CARD / SWITCH / FORCED_DEATH / FORCED_REACTION) |
    | `skill` / `skill_mask` | any | 匹配 `ctx.skill_index` |
    | `card_ref` | any | 匹配 `ctx.card_ref` |
    | `require_hit` | false | true → 仅当 `ctx.hit == true` 时触发 |

13. **强制切换不触发切换 buff**:`action_context == FORCED_*` SHALL NOT
    触发 `on_switch` 类 buff — 由 filter 默认值 `action_context != FORCED_*`
    保证。

## 4. Cross-references

**Sibling capability specs**:

- [`openspec/specs/engine-dsl/`](../engine-dsl/spec.md) — DSL hook 写法、
  declare-or-get pattern、mirror filter、HookType 枚举
- [`openspec/specs/engine-dice/`](../engine-dice/spec.md) — 骰子支付
  (`action_payments`)与本 spec 的动作枚举互补
- [`openspec/specs/engine-runtime/`](../engine-runtime/spec.md) — DSL 加载
  与隔离(本 spec 的 system DSL 由 runtime 加载)
- [`openspec/specs/engine-capi/`](../engine-capi/spec.md) — 动作 C API
  surface(`GameStep` / `GameGetLegalActions` / `GameGetActionRefs`)
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) — 格式
  与阈值

**History / postmortems**:

- `docs/1_specs/engine/actions.md` (deleted, migrated here) —
  本 spec 的 narrative source,已加 deprecation note,保留至 P1++
  整体清理
- `docs/1_specs/engine/README.md` (deleted, migrated here)
  §3 事件系统 / §4 伤害管道 — engine 数据模型与事件栈

**Memory cross-references**:

- Engine Ignorance 详 `memory feedback_engine_ignorance`
- Episode step bound(~340 actions / episode)详 `memory project_episode_step_bound`

## 5. Status

- **Created**:2026-05-15(P1-T4)
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/engine/actions.md`(122 行)
- **Expected revision triggers**:
  - HookActionCheck ctx 字段扩展(新 candidate kind 加入)
  - Forced switch 语义放开(若 reopen 消耗 AP / 翻转行动权)
  - 新 system DSL 文件加入(对照表扩充)
  - Filter 字段语义变更(新 filter 字段 / 默认值调整)
