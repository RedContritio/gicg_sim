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

```go
type CharInfo struct {
    PlayerIdx  int
    CharIdx    int
    SkillCount int   // 技能数量（引擎只枚举 0..N-1，不知道技能属性）
    Alive      bool
}

type CardInst struct {
    Ref int // 卡牌身份标识（DSL 用 card_ref 匹配 hook）
}

type PlayerState struct {
    Chars       []CharInfo
    ActiveChar  int
    Hand        []CardInst
    Deck        []CardInst
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
这些 counter 由 DSL 的 `declare_char` 和 `system/round.lua` 创建，引擎不持有引用。

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

## 9. Go-Python 接口

### 9.1 C API（cgo 导出）

```go
//export GameNew
func GameNew(configJSON *C.char) C.int

//export GameReset
func GameReset(gameID C.int, seed C.int64_t) C.int

//export GameGetState
func GameGetState(gameID C.int, buf *C.float, bufLen C.int) C.int

//export GameGetActionCount
func GameGetActionCount(gameID C.int) C.int

//export GameGetActions
func GameGetActions(gameID C.int, buf *C.int, bufLen C.int) C.int

//export GameStep
func GameStep(gameID C.int, actionIdx C.int) C.int  // 返回: 0=需要目标, 1=完成, 2=游戏结束

//export GameStepTarget
func GameStepTarget(gameID C.int, targetIdx C.int) C.int

//export GameGetReward
func GameGetReward(gameID C.int, player C.int) C.float

//export GameGetWinner
func GameGetWinner(gameID C.int) C.int  // -1=进行中, 0=P0胜, 1=P1胜, 2=平局

//export GameFree
func GameFree(gameID C.int)
```

### 9.2 Python Gymnasium 封装

```python
class CardGameEnv(gymnasium.Env):
    def __init__(self, config):
        self.lib = ctypes.CDLL("./libengine.so")
        self.game_id = self.lib.GameNew(json.dumps(config).encode())

    def reset(self, seed=None):
        self.lib.GameReset(self.game_id, seed or 0)
        return self._get_obs(), {}

    def step(self, action):
        status = self.lib.GameStep(self.game_id, action)
        if status == 0:  # 需要目标
            return self._get_obs(), 0, False, False, {"need_target": True}
        # ...

    def _get_obs(self):
        buf = (ctypes.c_float * self.obs_size)()
        self.lib.GameGetState(self.game_id, buf, self.obs_size)
        return np.frombuffer(buf, dtype=np.float32)
```
