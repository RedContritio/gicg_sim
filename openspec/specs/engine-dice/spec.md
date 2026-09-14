---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: engine-dice
---

# Engine Dice — 投掷 / 费用结构 / 支付枚举 / 调和 / 隐藏信息

> 本 capability spec 治理 GICG 骰子系统:8 种类型(7 元素 + 1 万能)、
> 投掷分布(每枚独立 1/8)、3 种费用原子(`n 同色` / `n 无色` / `n X 色`)、
> 3 种合法费用结构、支付枚举去重、切换费用、调和、零骰费用行动、隐藏
> 信息(公开总数量 + 私有类型分布)、回合结束丢弃约定。
>
> 本 spec 从 `docs/1_specs/engine/dice.md`(238 行)抽取规约,SHALL 化。
> 单 spec.md(权威源为代码,见 §1 引用)。
>
> 与 [`engine-actions`](../engine-actions/spec.md) 的边界:本 spec 治理
> 骰子本身(数据 / 枚举 / 支付),动作枚举与执行管道由 engine-actions
> 治理;`action_payments` 为骰子与动作的连接面,定义在本 spec。

## 1. Purpose

GICG 骰子系统需被规约化,否则会出现:

- 费用语法被无意扩展到不支持的结构(混合特定色 / 多个同色 / 特定色+同色)
- 支付枚举的多重集去重(`{冰,冰,火} == {火,冰,冰}`)在 refactor 中漏失,
  造成等价动作重复进入合法集
- 万能骰替代规则(可代任意颜色,纯万能合法满足 `n 同色`)在某个原子下
  被静默偏离
- 隐藏信息契约破坏:对手骰子总数应为公开信息、各类型分布为私有,确定化
  采样器应从匹配 `已知总数 + 1/8 投掷分布` 的多项分布中采样
- 调和(`tune`)的**上下文敏感**特性丢失 — "当前元素"应在执行时刻而非
  提交时刻读取,这是 MCTS 无法抽象调和选择的根因(D12)
- 回合结束丢弃约定被改为"结转",造成"每回合独立资源决策"假设被破坏

**Code authoritative**(本 spec 描述与代码冲突时以代码为准):

- 骰子池 / 元素:`gicg_engine/interp/dice.go`
- 费用求解 / 支付枚举:`gicg_engine/cost_payment.go`
- 行动级支付索引:`gicg_engine/interp/ruleset.go`(`BuildDiceIndex`)
- 确定化注入:`gicg_engine/capi/capi_actions.go`(`GameSetPlayerDice`)
- Python 适配:`training/paradigms/az/determinize.py`(骰子颜色采样)、
  `training/core/network/actor_critic.py` 的 payment 编码、
  `training/paradigms/az/mcts/`(`action_payments` 通过叶节点 eval)
- 测试:`gicg_engine/tests/dice_test.go`

## 2. Scope

**In scope**:

- 骰子类型(7 元素 + 1 万能,共 8 种)与投掷分布(每枚 1/8 均匀)
- 投掷时机(`on_round_start` 投 8 枚)+ 回合结束丢弃约定
- 计数器组承载(`Tag.Dice` / `PerPlayer` / 16 个 counter = 8 类 × 2 玩家)
- 3 种费用原子(`SameColor(n)` / `Void(n)` / `Specific(element, n)`)
- 3 种合法费用结构 + 不支持结构
- 支付枚举规则(每结构选项数 / 万能替代 / 多重集去重)
- 切换费用(`1 无色` / 回合内无次数上限)
- 调和(0 骰费用 / 消耗 1 张手牌 / 上下文敏感性)
- 零骰费用行动(无固有零费 + 增益可降至 0)
- 隐藏信息(总数公开 / 类型分布私有 / 公开支付泄露)
- MVP → 真实骰子前向兼容约定

**Out of scope**:

- 动作枚举主体(skill / card / switch / EndTurn)— 由
  [`engine-actions`](../engine-actions/spec.md) 治理
- 确定化采样器算法本体(CardPoolSpec + Bayes 升级路径)— 由
  [`search-ismcts/determinization.md`](../search-ismcts/determinization.md) 治理
- `dice_combo_proj` 网络头与 obs encoder — 由
  [`network-architecture`](../network-architecture/spec.md) 治理
- C API `GameSetPlayerDice` / `GameGetDiceCounts` 等 surface — 由
  [`engine-capi`](../engine-capi/spec.md) 治理

## 3. Core SHALL invariants

以下 14 条 invariant 是本 capability 的硬约束。任意冲突应作为 OpenSpec
change 提案修订,而非在代码中静默偏离。

### 3.1 投掷与丢弃

1. **8 种类型 + 每枚 1/8**:Dice SHALL be 7 元素 + 1 万能(共 8 种)。
   每枚 SHALL 独立以 `1/8` 均匀概率落在 8 种类型中的任意一种。每次
   `on_round_start` SHALL roll 8 枚。期望每回合获 1 枚万能骰。

2. **回合结束丢弃**:未使用的骰子 SHALL be discarded at round end —
   回合之间 SHALL NOT 结转。这使骰子管理为"每回合独立资源决策",
   而非多回合积累博弈。

3. **计数器组承载**:骰子池 SHALL be stored as counter group with
   `Tag.Dice`、`PerPlayer` scope — 8 类型 × 2 玩家 = 16 个 counter。
   `on_round_start` hook(在 DSL 中)SHALL 重投 16 个 counter。
   `on_card_play` / `on_skill_use` hook SHALL 按支付结构扣除对应 counter。

### 3.2 费用原子

4. **3 种费用原子**:Cost atoms SHALL be exactly 3 kinds:

    | 原子 | 含义 | 支付选择时机 |
    |------|------|------------|
    | `SameColor(n)` | n 枚同色非万能骰(纯万能视为隐含同色合法) | 支付时玩家选颜色 |
    | `Void(n)` | n 枚任意颜色骰(玩家自由组合) | 支付时玩家选多重集 |
    | `Specific(element, n)` | n 枚特定 element 骰(万能可代任意数量) | 不由玩家选(声明时固定) |

5. **万能骰替代**:Wildcard(omni)dice SHALL substitute for any single
   color in `SameColor` 与 `Specific`。`SameColor(n)` 中纯 n 枚万能骰
   SHALL 合法(视为同一隐含颜色,与原神 TCG 一致)。

### 3.3 费用结构

6. **3 种合法费用结构**:Cost structure SHALL be one of:

    - **纯同色** — `SameColor(n)`
    - **纯无色** — `Void(n)`
    - **特定色 + 无色** — `Specific(element, a) + Void(b)`

   其他结构 SHALL NOT 被费用语法支持 — 包括但不限于"混合特定色"
   (`1 火 + 1 冰 + 1 无色`)、"多个同色"(`3 同色 + 2 同色`)、
   "特定色 + 同色"(`2 火 + 3 同色`)。

### 3.4 支付枚举

7. **多重集去重**:Legal action enumeration SHALL deduplicate equivalent
   multiset payments — `{冰,冰,火}` 与 `{火,冰,冰}` SHALL be a single
   payment(骰子顺序无意义)。

8. **支付选项数上界**:Engine SHALL enumerate payments per cost structure
   按下表(受支付能力剪枝):

    | 结构 | 枚举规则 | 典型选项数 |
    |------|---------|----------|
    | `Specific(X, n)` | 万能替代级别 0..n,共 `n+1` 种 | 1-3 |
    | `SameColor(n)` | 7 颜色 × (n+1) 替代级别 + 纯万能归并 | 3-10 |
    | `Void(n)` | 池中可取 n 枚多重集组合,上界 `C(类型数+万能, n)` | n=2 ≤15 / n=3 ≤35 |
    | `Specific(X,a) + Void(b)` | 特定色选项 × 剩余池无色选项 | 5-30 |

   `Void(n)` SHALL be 行动空间增长的主要来源。

### 3.5 切换 / 调和 / 零费

9. **切换费用**:Switch active char SHALL cost `Void(1)` — 1 枚任意颜色
   骰(可万能代)。回合内 SHALL NOT have 切换次数上限 — 玩家可在一个
   回合中支付若干次 `Void(1)` 后任意切换。

10. **调和费用**:Tune SHALL cost `0 dice` + discard 1 hand card +
    convert 1 non-current-element non-omni die into current active
    char's element。SHALL NOT 额外消耗骰子。

11. **调和上下文敏感**:Tune 的"当前元素"SHALL be read at execution time
    (非提交时)— 若玩家在 queue 与 execute 之间切换角色,tune SHALL
    target 新出战角色的元素。这是 D12 决定 MCTS 不抽象调和的根因。

12. **零骰费用契约**:Initial 状态 SHALL NOT 有任何技能具有内在 0 骰费用 —
    每个技能 / 卡牌至少需要 1 枚骰子。增益可将费用降至 0
    (例如"本回合下一个技能费用为 0"),engine SHALL 通过现有
    `on_action_check` 类 hook 路径处理。调和 SHALL be 例外
    (本身 0 骰 + 弃 1 卡)。

### 3.6 隐藏信息

13. **隐藏信息维度**:对手骰子状态 SHALL be:总数量为公开信息,
    各类型具体分布为对对手而言私有。Determinization sampler SHALL 从
    `匹配已知总量 + 1/8 投掷分布` 的多项分布中采样 8 维向量,并 SHALL
    根据本回合对手已公开的支付历史进行调整(MVP 朴素均匀,升级到
    Bayesian 见 search-ismcts/determinization)。

### 3.7 前向兼容

14. **MVP → 真实骰子前向兼容**:MVP 代码 SHALL NOT 做出在真实骰子上线
    时会被破坏的假设:

    - `get_action_refs` 返回 `(kind, skill_ref, card_ref)` 三元组 — 真实
      骰子上线后 SHALL 附加 8 维骰子组合向量为第四字段
    - `MAX_ACTIONS` SHALL be cfg-driven 可增长至 128 / 256,SHALL NOT
      重构 policy head
    - Observation 维度 SHALL via engine query 获取(详
      [`network-architecture/obs.md`](../network-architecture/obs.md)),
      新增 16 个骰子 counter SHALL be cfg 变更而非重构
    - 行动特征计算(`hook_emb + target_proj`)SHALL 留 `dice_combo_proj`
      残差加法空间
    - MVP 引擎中虽不含费用可支付性检查,所用模式(engine 侧
      `GetLegalActions` 枚举可负担组合)SHALL 与骰子枚举同形

## 4. Cross-references

**Sibling capability specs**:

- [`openspec/specs/engine-actions/`](../engine-actions/spec.md) — 动作
  枚举与执行管道(`action_payments` 是两 spec 的连接面)
- [`openspec/specs/engine-capi/`](../engine-capi/spec.md) — 骰子相关 C API
  (`GameSetPlayerDice` / `GameGetDiceCounts` / `GameGetDiceColorCount` /
  `GameGetDicePaid` / `GameGetDiceTunedOut` / `GameGetDiceTunedIn`)
- [`openspec/specs/search-ismcts/determinization.md`](../search-ismcts/determinization.md) —
  确定化采样(骰子隐藏状态采样在采样器内部,本 spec 仅约束公私边界)
- [`openspec/specs/network-architecture/obs.md`](../network-architecture/obs.md) —
  RL obs 骰子布局(16 个 counter 槽位 + dice_combo_proj 投影)
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) — 格式
  与阈值

**History / decisions**:

- `docs/1_specs/engine/dice.md` (deleted, migrated here) —
  本 spec 的 narrative source,已加 deprecation note,保留至 P1++
  整体清理。设计原稿包括 D7(原"推迟"决策已端到端实现)和工作量估算
  (5-7 天)— 保留作历史
- 决策日志 D7 / D12 — 调和路径依赖 + MCTS 不抽象调和

## 5. Status

- **Created**:2026-05-15(P1-T4)
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/engine/dice.md`(238 行)
- **Expected revision triggers**:
  - 新费用原子或结构加入(本 spec 明确 SHALL NOT 支持,新结构需 change)
  - 调和上下文语义放开(若 reopen "提交时读取元素")
  - 回合结束骰子结转(若开"积累博弈"模式)
  - 确定化采样器升级到 Bayesian 后,公开支付信息利用条款细化
