# 技能 DSL 设计文档

## 设计理念

采用**纯 DSL（领域特定语言）方案**。DSL 的“语义层”独立于具体写法：既可以用 YAML/JSON 这类结构化格式承载，也可以用自定义的简易脚本语法承载；实现上不依赖通用脚本语言（如 Lua/JS）去写业务逻辑。

### 核心原则

1. **完全配置化**：所有技能逻辑都在配置文件中
2. **声明式语法**：易读、易写、易维护
3. **功能完整**：支持条件、表达式、循环等复杂逻辑
4. **类型安全**：配置验证确保正确性
5. **特征提取**：DSL 结构便于提取特征用于 RL 训练
6. **可扩展性**：支持未来新卡牌类型和效果的扩展

## 卡牌类型支持

基于 `data/` 目录中的卡牌分析，DSL 需要支持以下卡牌类型：

1. **角色技能**：普通攻击、元素战技、元素爆发
2. **装备牌**：天赋、武器、圣遗物
3. **事件牌**：普通事件、料理、秘传等
4. **支援牌**：场地、角色支援等

## 语义词汇表（实现视角：Token + Hook）

这一节把我们讨论的“用 token 表达时效/次数限制，用 hook 在事件点修改结算”的**词义**说清楚。语法是表现层，真正实现时建议先把这些词落到统一的**事件上下文（Context）**与**过滤器（Filter）**上。

### 核心对象（Object）

- **实体（Entity）**：可以挂 token、可以作为 source/target 的对象。最常见的实体类型：
  - **character**（角色）
  - **card_instance**（某张卡牌的在场实例：装备/支援/召唤物等）
  - **side**（一方：self/opponent）
  - **game**（全局）
- **Token**：挂在某个实体上的标记/数据记录（不是自然语言）。token 名是**纯标识符**，不把“+3/火伤/爆发”等语义写进名字里。
- **Hook**：对某类事件的订阅；事件发生时，在指定阶段点执行一段 DSL 指令（可读写 Context 的部分字段，例如伤害数值）。

### 事件（Event）与默认上下文（Context）

以下事件名建议固定成枚举；每个事件都有一份上下文（只列核心字段）：

- **`play_card`**（打出卡牌）
  - `side`：出牌方（self/opponent）
  - `card`：被打出的卡牌实例
  - `target`：被指定目标（若该牌需要选择目标）
- **`equip_card` / `unequip_card`**（装备/卸下装备）
  - `owner`：装备持有者角色
  - `card`：装备牌实例
- **`use_skill`**（使用技能，尚未结算伤害）
  - `source`：使用技能的角色
  - `skill.type`：`normal_attack | elemental_skill | elemental_burst`
  - `skill.name/id`：技能标识
- **`damage`**（造成伤害，建议默认指“结算前、可修改数值”的点）
  - `source`：伤害来源实体（通常是角色/召唤物）
  - `target`：受伤实体（通常是角色）
  - `damage.amount`：可变（hook 可改）
  - `damage.element`：`physical | pyro | hydro | cryo | electro | dendro | anemo | geo`
  - `damage.is_piercing`：是否穿透伤害
  - `damage.is_reaction`：是否由元素反应产生/放大（由引擎定义）
  - `skill.type`：若该伤害来自技能，则填同上；否则为 `null`
  - `reaction.type`：若有，填 `vaporize | melt | overload | ...`；否则 `null`
- **阶段事件（Phase）**（用于群玉阁/秘传等）
  - `roll_phase_start`（投掷阶段开始）
  - `action_phase_start`（行动阶段开始）
  - `end_phase_start`（结束阶段开始）
  - `round_end`（一轮结束：用于“回合结束清理 token”）

> 约定：**“回合结束自动清理”**在实现里统一落到 `round_end`（或你引擎里的等价时点）事件做批量清理。

### 过滤词（Filter Term）的含义（解决“下一次火伤/物伤/爆发/战技 +X”）

`hook on damage <term...>` 的 `<term...>` 是一组**并且（AND）**条件；每个 term 只对应**一个**明确字段判断，不要自然语言歧义：

- **技能类型类**
  - `normal_attack`：`ctx.skill.type == normal_attack`
  - `elemental_skill`：`ctx.skill.type == elemental_skill`
  - `elemental_burst`：`ctx.skill.type == elemental_burst`
- **伤害元素类**
  - `pyro/hydro/.../geo/anemo/dendro/electro/cryo`：`ctx.damage.element == <element>`
  - `physical`：`ctx.damage.element == physical`
- **伤害性质类**
  - `piercing`：`ctx.damage.is_piercing == true`
  - `reaction`：`ctx.damage.is_reaction == true`（且可进一步加 `reaction_type`）
  - `reaction:<type>`：`ctx.reaction.type == <type>`（例如 `reaction:melt`）

示例：  
`hook on damage elemental_burst pyro` 等价于：
`ctx.skill.type == elemental_burst AND ctx.damage.element == pyro`

### Token 的作用域（Scope）与生命周期（TTL）

建议把 token 统一成 `(scope, name, payload, ttl)`：

- **scope**（挂在哪个实体上）
  - `on <character>`：角色级（常用于“每回合1次”“下一次”）
  - `on <side>`：阵营级（常用于“本回合我方下次打出…减少费用”）
  - `global`：全局级（常用于“整局只能一次”）
- **ttl**（何时自动清理）
  - `round`：在 `round_end` 自动清理（用于“本回合/每回合”）
  - `game`：不自动清理（用于“整局”）
- **payload**（可选数据，避免把语义塞进 token 名）
  - 最小可用：`value: int`（例如 +3、次数剩余）
  - 常用扩展：`uses: int`（剩余可用次数），`tag: enum`（用于区分同类 token）

### 指令词（Instruction）的精确定义（最小集合）

（这里不追求多，而追求“每个词都能落到引擎操作”）

- **`token <scope> <name> [value <int>] [ttl round|game]`**
  - 在指定 scope 上设置 token；若已存在则覆盖/合并（需在实现里定规则，推荐：覆盖）
- **`has <scope> <name>` / `not has ...`**
  - 查询 token 是否存在（存在即 true；不解析名字内容）
- **`remove <scope> <name>`**
  - 移除 token
- **`modify damage +<int>` / `modify damage -<int>`**
  - 仅在 `damage` 事件上下文中有效：修改 `ctx.damage.amount`
- **`fail "<reason>"`**
  - 终止本次事件处理（通常用于“不能打出/不能触发”）

### 用 token 表达“下一次/每回合一次/整局一次”（统一范式）

- **下一次 X +N**
  - `token ... "boost" value N ttl round`
  - `hook on damage <filters...>:` 若命中且 `has boost`，则 `modify damage + value`，然后 `remove boost`
- **每回合 1 次**
  - `hook ...:` 若 `not has "used"` 才执行；执行后 `token ... "used" ttl round`
- **整局 1 次**
  - 同上，但 `ttl game`（不清理）

> 关键点：**差异都体现在 hook 的过滤器与 token 的 scope/ttl 上**；实现端只需要“事件 + 上下文 + 过滤器匹配 + token 管理 + 指令执行”这几块通用能力。

