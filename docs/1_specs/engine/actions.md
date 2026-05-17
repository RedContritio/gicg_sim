# 引擎设计 — 动作 / 回合 / 系统规则 / Filter

> **MOVED to `openspec/specs/engine-actions/`**（2026-05-15，P1-T4）
>
> 本文档内容已迁到 OpenSpec（SHALL 语言）。
> 新 spec:[engine-actions/spec.md](../../../openspec/specs/engine-actions/spec.md)
> 本文件保留至 P1++（`docs/1_specs/` 整体清理）；**只读**。

---

> 本文是 `README.md` 的延续。前置阅读：`README.md` 第 1-4 节（引擎职责、数据模型、事件系统、伤害管道）。

## 5. 动作系统

### 5.1 候选枚举

引擎 `GetLegalActions` 只做结构化枚举，不做任何条件判断：

```
候选列表:
  技能: 出战角色的 skill 0..N-1
  卡牌: 手牌中每张牌
  切换: 其他存活角色
  结束回合: 始终可用
```

### 5.2 HookActionCheck 过滤

每个候选过一遍 `HookActionCheck`，ctx.playable 默认 true，hook 可置 false：

```
for 每个候选:
  ctx = { playable=true, 候选信息(kind, skill_index, card_ref...) }
  fire HookActionCheck
  if ctx.playable → 加入合法列表
```

由 DSL 实现的检查（全部通过 HookActionCheck）：
- AP 不足 → `system/round.lua`
- 能量不足 → 各技能 `declare_skill` 注册
- 冻结 → `system/frozen.lua`
- 饱腹 → `system/food.lua`
- 卡牌专属条件 → 各卡牌 `on_action_check`

### 5.3 动作执行

```
HookActionPrepare
  ctx = { ap_cost, energy_cost, battle_action, ... }
  DSL hook 可修改（减费、快速行动翻转等）
  引擎读取最终 ctx 值

pushEvent(动作帧)

DSL 扣费（通过 ActionPrepare 中的 hook 或技能 hook）

HookSkillUse / HookCardPlay / HookSwitch
  按 filter 匹配触发对应 DSL hook

popEvent

HookBeforeTurnFlip
  ctx.battle_action 可被 hook 修改
  if ctx.battle_action → 翻转行动权
```

### 5.4 强制切换

死亡/超载产生的强制切换通过延后队列进入：
- `action_context = FORCED_DEATH / FORCED_REACTION`
- 不消耗 AP，不翻转行动权
- 需要玩家选择目标 → 暂停管道返回

## 6. 回合框架

引擎只推进阶段和触发 hook，所有规则由 `system/` DSL 实现。

```
NewRound:
  Round++
  fire HookRoundStart
    └─ round.lua: AP 重置、先手判定
    └─ energy.lua: 能量分配
    └─ 各 counter 的重置 hook
  Phase = Action

EndPhase:
  Phase = RoundEnd
  fire HookRoundEnd            状态结算（先手方 → 后手方）
  fire HookRoundEndPostSummon  召唤物结算
  fire HookRoundEndDecay       持续时间衰减
  fire HookRoundEndFinal       draw.lua 抽牌、timeout.lua 判负
  if !GameOver → NewRound
```

## 7. 系统规则 DSL

以下规则在 `data/system/` 中以 DSL 形式实现（而非硬编码在引擎中）：

| 文件 | 职责 | 使用的引擎机制 |
|------|------|---------------|
| `round.lua` | 创建 AP counter（per_player scope）；HookRoundStart 中重置 AP、判定先手 | counter + HookRoundStart + HookActionCheck（AP 检查） |
| `death.lua` | on_after_write(hp, SUB) 检测 HP≤0 → set_alive(false) → defer 强制切换 | counter + on_after_write + defer + set_alive |
| `energy.lua` | HookRoundStart 分配能量；HookAfterDamage(require_hit) 技能获取能量 | counter + HookActionCheck（能量检查） |
| `frozen.lua` | HookActionCheck 检查冻结 counter → 阻止技能和切换 | counter + HookActionCheck |
| `draw.lua` | HookRoundEndFinal 中双方各抽 2 张；开局抽 5 张 | draw_card() |
| `timeout.lua` | HookRoundStart(round==1) 记录先手方 counter；HookRoundEndFinal 判负 | counter + set_winner |
| `food.lua` | 食物使用 → 设置饱腹 counter；HookActionCheck 阻止再次使用食物 | counter + HookActionCheck |

## 8. Filter 机制

### 8.1 actor 过滤

| Filter 值 | 匹配条件 | 典型用途 |
|-----------|---------|---------|
| `SELF` | hook.OwnerChar == ctx.ActorChar | self scope：角色自身效果 |
| `ACTIVE` | Players[hook.OwnerPlayer].ActiveChar == ctx.ActorChar | active_status scope：出战角色效果 |

`SELF` 是角色级匹配，`ACTIVE` 是槽位级匹配。`active_status` scope 的 hook 搭配 `ACTIVE` filter，确保只匹配当前出战角色的行动，后台角色被 invoke_skill 触发时不匹配。

### 8.2 其他 filter 字段

| 字段 | 默认值 | 含义 |
|------|--------|------|
| `source` | any | 匹配 ctx.source（SKILL, CARD, STATUS...） |
| `action_context` | any | 匹配 ctx.action_context（USE_SKILL, PLAY_CARD...） |
| `skill` / `skill_mask` | any | 匹配 ctx.skill_index |
| `card_ref` | any | 匹配 ctx.card_ref |
| `require_hit` | false | true = 仅当 ctx.hit==true 时触发 |

