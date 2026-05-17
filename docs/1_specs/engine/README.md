# 引擎设计

## 1. 引擎职责

引擎是**通用框架**，不包含任何游戏规则知识。

引擎知道的概念：角色（身份、存活、技能数量）、手牌（身份标识）、牌堆、回合、行动轮。

引擎不知道的概念：HP、能量、元素、护盾、冻结、AP、战斗/快速行动——这些全部是 DSL 层概念，通过 counter + hook 实现。

引擎提供的能力：
- Counter 存储（flat 数组，clamp，写入管道）
- Hook 调度（注册、按类型/counter 分发、filter 匹配）
- 事件栈管理（嵌套上下文 + 延后队列）
- 动作候选枚举（纯结构化枚举，不做任何条件判断）
- 管道框架（伤害管道、回合阶段）
- Shuffle（观测导出时的 counter/hook 排列）

## 2. 引擎数据模型

See `gicg_engine/game.go` for the canonical definitions. Snapshot:

```go
type CharInfo struct {
    PlayerIdx int
    CharIdx   int
    Skills    []int   // global skill IDs attached to this char binding
    Alive     bool
}

type CardInst struct {
    Ref          int  // 卡牌身份标识（DSL 用 card_ref 匹配 hook）
    DrawnAtRound int  // 进入手牌时的 Round，用于 reward shaping 的 held-time decay
}

type PlayerState struct {
    Chars       []CharInfo
    ActiveChar  int
    Hand        []CardInst
    Deck        []CardInst
    Discard     []CardInst  // 弃牌堆（打出的卡进这里）
    InitDeck    []CardInst  // Reset() 时恢复
    DeclaredEnd bool
}

type Counter struct {
    Value int
    Init  int  // Game.Reset() 时恢复
    Min   int
    Max   int
}
```

注意：无 HPCounterID、EnergyCounterID、FreezeCounterID、APCounterID。
这些 counter 由 DSL 的 `declare_char` 和 `system/round.lua` 创建，引擎不持有引用。`Game.RewardAccum[2]RewardEvents` 累积 per-step 事件计数，由 capi 的 `GameGetRewardEvents` 导出给 Python；引擎自身不计算 reward 公式。

## 3. 事件系统

### 3.1 事件帧

每个对玩家可见的动作 push 一帧到事件栈，完成后 pop：

| 操作 | push 帧 | 说明 |
|------|---------|------|
| `executeSkill` | `[ActUseSkill, SrcSkill, player, char]` | 动作入口 |
| `executeCard` | `[ActPlayCard, SrcCard, player, char]` | 动作入口 |
| `executeSwitch` | `[ActSwitch/ActForcedDeath, SrcNone, player, char]` | 动作入口 |
| `deal_damage` | `[继承ActionCtx, opts.source覆盖, opts.actor覆盖]` | 每次 deal_damage 自带帧 |
| `heal` | `[继承ActionCtx, opts.source覆盖, opts.actor覆盖]` | 同上 |
| `switch_active` | `[继承ActionCtx, SrcNone, player, new_char]` | DSL 调用 |

**帧覆盖规则**：opts 中指定的 source/actor 覆盖继承值，未指定则继承外层栈。
这确保嵌套调用（如刺刺猫爪反击 `deal_damage({source=STATUS, actor=猫咪})`）不会继承错误的来源。

### 3.2 两层事件上下文

| 层级 | 字段 | 取值 | 用途 |
|------|------|------|------|
| 动作上下文 | `ctx.action_context` | USE_SKILL, PLAY_CARD, SWITCH, FORCED_DEATH, FORCED_REACTION | 因果链顶层：玩家选择了什么 |
| 直接来源 | `ctx.source` | SKILL, CARD, STATUS, SUMMON, SUPPORT, REACTION | 当前效果的直接产生者 |

强制切换（死亡、超载）携带 `action_context = FORCED_*`，不会触发切换相关 buff。

### 3.3 延后队列

事件栈每层是一个**队列**，而非单帧：

```
栈: [ [A], [B], [C, D, E] ]
              栈顶队列 ↑
```

- C 是当前执行的事件
- D、E 是 C 执行过程中通过 `defer` 追加的衍生事件
- C 完成后，按顺序执行 D、E
- 若 C 执行中 push 了新帧（嵌套），新帧在更高层优先处理完再回来
- 队列清空后，弹出栈顶，回到上一层

用途：
- 元素反应在 ② 阶段 defer 状态副作用（冻结、超载强制切换），在 ④ 之后执行
- 需要玩家决策的延后事件（强制切换）暂停管道，返回等待输入

## 4. 伤害管道

`deal_damage(target, element, value, opts)` 进入引擎管理的管道：

```
pushEvent(帧)

① HookBeforeDamage
   可修改：ctx.value, ctx.element, ctx.skip_reaction
   ctx.cancelled = true → 整体取消，return

② HookReactionDamage（仅 !skip_reaction）
   系统反应 hook：检查目标元素附着 + ctx.element
   ─ 可反应：修改 ctx.value（加伤），清除附着，defer 状态副作用
   ─ 不可附着元素（岩/物理/无）：跳过
   ─ 无附着且可附着：设置附着

③ FireBeforeWrite(target_hp, SUB)（仅 !penetrate）
   护盾 hook 吸收 ctx.value
   cancel() 或吸收后 value≤0 → 跳过 ④，仍执行 drain + ⑤

④ HP 扣减（ctx.value > 0 时）
   ApplyWrite(target_hp, SUB, ctx.value)
   ctx.hit = true
   FireAfterWrite(target_hp, SUB)
   └─ death.lua 在此检测 HP≤0

drain deferred（② 中 defer 的反应状态副作用在此执行）

⑤ HookAfterDamage
   始终触发（无论 ③ 是否吸收、ctx.hit 是否为 true）
   filter.require_hit = true 可限定"仅实际命中时触发"

popEvent
```

递归保护：`deal_damage` 和 `WriteCounter` 入口递增 depth，超过 MaxDepth(16) 跳过。



---

继续阅读：
- 动作系统 / 回合框架 / 系统规则 / Filter — moved to [`openspec/specs/engine-actions/`](../../../openspec/specs/engine-actions/spec.md)（P1-T4；narrative source `actions.md` 只读保留）
- Go-Python 接口 / mirror match per-binding loading / card draw 元数据 — moved to [`openspec/specs/engine-capi/`](../../../openspec/specs/engine-capi/spec.md)（P1-T4；narrative source `capi_mirror.md` 只读保留）
- 骰子系统 — moved to [`openspec/specs/engine-dice/`](../../../openspec/specs/engine-dice/spec.md)（P1-T4；narrative source `dice.md` 只读保留）
- Runtime 加载 / 拓扑 / 沙箱 — [`openspec/specs/engine-runtime/`](../../../openspec/specs/engine-runtime/spec.md)（P1-T4）
- [`dsl/`](dsl/) — Lua DSL 子集 (api / conventions / structure)（DSL 作者面向规约由 [`openspec/specs/engine-dsl/`](../../../openspec/specs/engine-dsl/spec.md) 治理）
