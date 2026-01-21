# 技能 DSL 设计文档

## 设计理念

采用**纯 DSL（领域特定语言）方案**，所有技能逻辑（包括主动技能、被动技能、触发条件等）都通过 YAML 配置文件描述，不使用任何脚本语言。

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

## DSL 语法

### 卡牌基础结构

```yaml
card:
  id: "card_id"                      # 卡牌唯一标识
  name: "卡牌名称"                    # 卡牌显示名称
  type: "equipment" | "event" | "support" | "skill"
  
  # 卡牌子类型（用于分类和限制）
  subtype: "talent" | "weapon" | "artifact" | "food" | "location" | ...
  
  # 元数据（用于特征编码和 RL 训练）
  metadata:
    damage_type: "physical" | "elemental"
    base_damage: 2
    target_type: "active_character" | "all_characters"
    cost_type: "dice" | "energy" | "dice_energy"
    cost_value: 3
    
  # 消耗（可选）
  cost:
    dices:
      any: 3                         # 任意骰子数量
      matching: 0                    # 匹配元素骰子数量
      element: "pyro" | null         # 指定元素骰子数量
      same_color: true | false       # 同色骰子
      omni: 0                        # 万能元素数量
    energy: 0                        # 能量消耗
    
  # 使用限制
  restrictions:
    deck_requirement:                # 牌组要求
      character_id: "character_1101" # 需要特定角色
      min_characters: 2              # 最少角色数量
      element: "pyro"                # 需要特定元素角色
    play_limit:                      # 打出限制
      per_turn: 1                    # 每回合最多打出次数
      per_game: 1                    # 整局游戏最多打出次数
      per_character: 1               # 每个角色最多使用次数（如料理）
    condition: {...}                 # 打出条件（如"手牌数量不多于3"）
    
  # 装备条件（装备牌使用）
  equip_condition:
    character_id: "character_1102"   # 需要特定角色
    character_type: "sword"          # 需要特定武器类型
    active_character: true           # 必须是出战角色
    
  # 装备时立即效果（装备牌使用）
  on_equip:
    - type: "use_skill"              # 立即使用技能
      skill_id: "skill_11012"
    - {...}                          # 其他效果
    
  # 触发条件（被动效果使用）
  trigger:
    type: "on_damage_dealt" | "on_damage_taken" | "on_skill_use" | ...
    condition: {...}                 # 可选，进一步限制条件
    limit:                           # 触发限制
      per_turn: 1                    # 每回合最多触发次数
      per_round: 1                   # 每轮最多触发次数
    
  # 效果列表
  effects:
    - {...}                          # 效果定义
```

### 技能基础结构（角色技能专用）

```yaml
skill:
  id: "skill_id"                    # 技能唯一标识
  name: "技能名称"                    # 技能显示名称
  type: "normal_attack" | "elemental_skill" | "elemental_burst" | "passive"
  
  # 元数据（用于特征编码和 RL 训练）
  metadata:
    damage_type: "physical" | "elemental"
    base_damage: 2
    target_type: "active_character" | "all_characters"
    cost_type: "dice" | "energy" | "dice_energy"
    cost_value: 3
    
  # 消耗（可选）
  cost:
    dices:
      any: 3                         # 任意骰子数量
      matching: 0                    # 匹配元素骰子数量
      element: "pyro" | null         # 指定元素骰子数量
    energy: 0                        # 能量消耗
    
  # 触发条件（被动技能使用）
  trigger:
    type: "on_damage_dealt" | "on_damage_taken" | "on_skill_use" | ...
    condition: {...}                 # 可选，进一步限制条件
    
  # 效果列表
  effects:
    - {...}                          # 效果定义
```

## 效果类型

### 1. 伤害效果

```yaml
- type: "damage"
  value: 2                           # 固定伤害值
  # 或使用表达式
  value:
    type: "expression"
    formula: "base_damage + bonus"
    variables:
      base_damage: 2
      bonus: 1
  element: "physical" | "pyro" | "hydro" | ...
  target: "opponent_active_character" | "all_opponent_characters" | ...
  can_crit: true | false
```

### 2. 治疗效果

```yaml
- type: "heal"
  value: 3
  target: "self_active_character" | "all_self_characters" | ...
```

### 3. 状态效果

```yaml
# 添加 Buff/Debuff
- type: "add_status"
  status_type: "attack_boost" | "defense_boost" | "elemental_mastery" | ...
  value: 2
  duration: 3                         # 持续回合数
  target: "self_active_character"

# 移除状态
- type: "remove_status"
  status_type: "attack_boost"
  target: "opponent_active_character"
```

### 4. 元素反应

```yaml
- type: "elemental_reaction"
  reaction_type: "vaporize" | "melt" | "overload" | ...
  source_element: "pyro"
  target_element: "hydro"
  multiplier: 2.0
```

### 5. 切换角色

```yaml
- type: "switch_character"
  character_id: "character_2"
  # 或
  character_index: 1
```

### 6. 卡牌操作

```yaml
# 抽牌
- type: "draw_card"
  count: 2

# 弃牌
- type: "discard_card"
  count: 1
  filter:                            # 可选过滤
    type: "card_type"
    value: "equipment"
```

### 7. 骰子操作

```yaml
# 调和骰子
- type: "tune_dice"
  from: "pyro"
  to: "hydro"
  count: 1

# 投掷骰子
- type: "roll_dice"
  count: 2

# 添加骰子
- type: "add_dice"
  element: "omni"
  count: 1
```

### 8. 召唤物/支援牌

```yaml
# 召唤物
- type: "summon"
  summon_id: "summon_fire"
  duration: 2
  usage: 1                           # 可用次数
  effects:                           # 召唤物效果
    - type: "damage"
      value: 1
      trigger: "on_turn_end"

# 支援牌
- type: "add_supporter"
  supporter_id: "supporter_liyue"
  duration: null                     # null 表示永久

# 移除召唤物/支援牌
- type: "remove_summon"
  summon_id: "summon_fire"
  
- type: "remove_supporter"
  supporter_id: "supporter_liyue"
```

### 9. 费用减免效果

```yaml
# 技能费用减免
- type: "reduce_skill_cost"
  skill_type: "normal_attack" | "elemental_skill" | "elemental_burst" | "all"
  reduction: 1                       # 减免数量
  element: "omni" | "pyro" | null    # 减免的骰子类型
  duration: 1                         # 持续回合数
  count: 1                           # 生效次数（如"下次使用技能"）

# 切换角色费用减免
- type: "reduce_switch_cost"
  reduction: 1
  duration: 1
  count: 2                           # 下2次切换角色

# 卡牌费用减免
- type: "reduce_card_cost"
  card_type: "equipment" | "event" | "support" | "all"
  card_subtype: "weapon" | "artifact" | null
  reduction: 2
  duration: 1
  count: 1
```

### 10. 伤害加成/减免效果

```yaml
# 伤害加成
- type: "damage_boost"
  skill_type: "normal_attack" | "elemental_skill" | "elemental_burst" | "all"
  value: 3                           # 加成数值
  duration: 1                         # 持续回合数
  count: 1                           # 生效次数（如"下一次技能"）
  target: "self_active_character"    # 目标角色

# 伤害减免
- type: "damage_reduction"
  value: 2                           # 减免数值
  duration: 1
  count: 1                           # 生效次数（如"下次受到的伤害"）
  target: "self_active_character"
```

### 11. 卡牌操作扩展

```yaml
# 加入手牌（指定卡牌）
- type: "add_card_to_hand"
  card_id: "card_215111"             # 指定卡牌ID
  count: 1

# 加入手牌（随机卡牌）
- type: "add_random_card_to_hand"
  filter:                            # 过滤条件
    type: "equipment"
    subtype: "artifact"
  count: 1

# 窃取手牌
- type: "steal_card"
  filter:                            # 可选，过滤条件
    cost_highest: true               # 窃取费用最高的牌
  count: 1

# 弃置卡牌（指定区域）
- type: "discard_card"
  from: "hand" | "deck" | "support" | "summon"
  filter:                            # 可选过滤
    type: "card_type"
    value: "equipment"
  count: 1
```

### 12. 角色操作

```yaml
# 复苏角色
- type: "revive_character"
  target: "self_active_character" | "target_character"
  heal: 1                            # 复苏后治疗量

# 增加最大生命值
- type: "increase_max_hp"
  value: 1
  target: "self_active_character"
```

### 13. 骰子操作扩展

```yaml
# 投掷阶段效果
- type: "dice_roll_modifier"
  phase: "roll_phase"                # 投掷阶段
  effect: "guarantee_elements"       # 保证元素类型
  count: 2                           # 保证数量
  element: "character_element"       # 角色元素类型

# 生成特定元素骰子
- type: "add_dice"
  element: "omni" | "pyro" | "hydro" | ...
  count: 2
```

### 14. 条件效果

```yaml
# 条件触发效果（用于装备牌等）
- type: "conditional_effect"
  condition: {...}                   # 条件定义
  then:                              # 满足条件时的效果
    - type: "damage"
      value: 2
  else:                              # 不满足条件时的效果（可选）
    - type: "damage"
      value: 1
```

### 15. 随机选择效果

```yaml
# 从多个效果中随机选择
- type: "random_choice"
  count: 1                           # 选择数量
  options:                            # 选项列表
    - type: "heal"
      value: 2
    - type: "damage"
      value: 1
    - type: "draw_card"
      count: 1
```

### 16. 技能使用效果

```yaml
# 立即使用技能
- type: "use_skill"
  skill_id: "skill_11012"            # 技能ID
  skill_name: "霜袭"                  # 或使用技能名称
```

### 17. 状态修改效果

```yaml
# 修改状态值
- type: "modify_status"
  status_type: "attack_boost"
  operation: "add" | "set" | "multiply"
  value: 1
  target: "self_active_character"
```

### 18. 穿透伤害

```yaml
# 穿透伤害（对后台角色造成伤害）
- type: "piercing_damage"
  value: 2
  target: "all_opponent_backend_characters"
```

## 条件表达式

### 条件类型

```yaml
# 生命值条件
condition:
  type: "hp_below" | "hp_above" | "hp_equal"
  target: "self_active_character" | "opponent_active_character"
  threshold: 5

# 能量条件
condition:
  type: "energy_below" | "energy_above" | "energy_equal"
  target: "self_active_character"
  threshold: 2

# 状态条件
condition:
  type: "has_status" | "not_has_status"
  target: "self_active_character"
  status_type: "attack_boost"

# 元素条件
condition:
  type: "element_is" | "element_is_not"
  target: "self_active_character"
  element: "pyro"

# 手牌数量条件
condition:
  type: "hand_size_below" | "hand_size_above" | "hand_size_equal"
  side: "self" | "opponent"
  threshold: 5

# 骰子条件
condition:
  type: "dice_count_below" | "dice_count_above" | "dice_count_equal"
  side: "self"
  element: "pyro" | null              # null 表示任意元素
  threshold: 3

# 卡牌条件
condition:
  type: "has_card" | "not_has_card"
  side: "self" | "opponent"
  location: "hand" | "deck" | "support" | "summon"
  filter:                              # 卡牌过滤
    type: "equipment"
    subtype: "weapon"

# 装备条件
condition:
  type: "has_equipment" | "not_has_equipment"
  target: "self_active_character" | "all_self_characters"
  equipment_type: "weapon" | "artifact" | "talent"

# 召唤物/支援牌条件
condition:
  type: "has_summon" | "has_supporter"
  side: "self" | "opponent"
  summon_id: "summon_fire"            # 可选，指定召唤物ID
  count: 1                            # 可选，数量要求

# 技能使用条件
condition:
  type: "skill_used" | "skill_not_used"
  skill_id: "skill_11013"             # 技能ID
  skill_name: "霜华矢"                 # 或使用技能名称
  in_game: true | false               # 是否在本场对局中使用过

# 伤害条件
condition:
  type: "damage_above" | "damage_below" | "damage_equal"
  threshold: 2
  element: "pyro" | null              # 可选，元素类型

# 元素反应条件
condition:
  type: "reaction_triggered"
  reaction_type: "vaporize" | "melt" | "overload" | ...

# 召唤物/支援牌数量条件
condition:
  type: "summon_count" | "supporter_count"
  side: "self" | "opponent"
  operator: ">=" | "<=" | "=="
  threshold: 4

# 组合条件
condition:
  type: "and" | "or" | "not"
  conditions:
    - type: "hp_below"
      target: "opponent_active_character"
      threshold: 5
    - type: "has_status"
      target: "self_active_character"
      status_type: "attack_boost"
```

## 数值表达式

### 表达式类型

```yaml
# 固定值
value: 2

# 变量引用
value:
  type: "variable"
  name: "base_damage"

# 算术表达式
value:
  type: "expression"
  formula: "base_damage * multiplier + bonus"
  variables:
    base_damage: 2
    multiplier: 1.5
    bonus: 1

# 条件表达式（三元运算符）
value:
  type: "if"
  condition:
    type: "hp_below"
    target: "opponent_active_character"
    threshold: 5
  then: 3
  else: 2

# 函数调用
value:
  type: "function"
  name: "min" | "max" | "abs" | "get_hp" | "get_energy" | ...
  args:
    - 5
    - 
      type: "variable"
      name: "damage"
```

### 内置函数

- **数学函数**：`min(a, b)`, `max(a, b)`, `abs(x)`, `floor(x)`, `ceil(x)`, `round(x)`
- **游戏状态函数**：
  - `get_hp(target)` - 获取生命值
  - `get_max_hp(target)` - 获取最大生命值
  - `get_energy(target)` - 获取能量
  - `get_max_energy(target)` - 获取最大能量
  - `get_status_value(target, status_type)` - 获取状态值
  - `get_character_element(character_id)` - 获取角色元素类型
- **计数函数**：
  - `count_cards(side, location, filter)` - 统计卡牌数量
  - `count_dices(side, element)` - 统计骰子数量
  - `count_characters(side)` - 统计角色数量
  - `count_summons(side, summon_id)` - 统计召唤物数量
  - `count_supporters(side, supporter_id)` - 统计支援牌数量
- **查询函数**：
  - `has_card(side, location, filter)` - 检查是否有卡牌
  - `has_equipment(target, equipment_type)` - 检查是否装备
  - `has_status(target, status_type)` - 检查是否有状态
  - `get_card_cost(card_id)` - 获取卡牌费用
  - `get_skill_cost(skill_id)` - 获取技能费用
- **随机函数**：
  - `random(min, max)` - 随机整数
  - `random_choice(list)` - 随机选择
- **游戏历史函数**：
  - `skill_used_in_game(skill_id)` - 检查技能是否在本局使用过
  - `card_played_in_game(card_id)` - 检查卡牌是否在本局打出过
  - `get_turn_count()` - 获取当前回合数
  - `get_round_count()` - 获取当前轮次数

## 控制流

### 序列效果

```yaml
- type: "sequence"
  effects:
    - type: "damage"
      value: 2
    - type: "heal"
      value: 1
    - type: "add_status"
      status_type: "attack_boost"
      value: 1
```

### 循环效果

```yaml
- type: "repeat"
  count: 3                            # 固定次数
  # 或使用表达式
  count:
    type: "function"
    name: "count_characters"
    args: ["opponent"]
  effect:
    type: "damage"
    value: 1
    target: "opponent_active_character"
```

### 条件分支

```yaml
- type: "if"
  condition:
    type: "hp_below"
    target: "opponent_active_character"
    threshold: 5
  then:
    - type: "damage"
      value: 3
  else:
    - type: "damage"
      value: 2
```

## 被动技能和触发器

### 触发器类型

```yaml
# 造成伤害时
trigger:
  type: "on_damage_dealt"
  condition:                          # 可选
    type: "damage_above"
    threshold: 2

# 受到伤害时
trigger:
  type: "on_damage_taken"
  condition:
    type: "element_is"
    target: "source"
    element: "pyro"

# 使用技能时
trigger:
  type: "on_skill_use"
  condition:
    type: "skill_type_is"
    skill_type: "elemental_skill"
  skill_id: "skill_11012"             # 可选，指定技能ID
  skill_name: "霜袭"                  # 可选，指定技能名称

# 使用特定技能时（如"霜华矢"）
trigger:
  type: "on_specific_skill_use"
  skill_id: "skill_11013"
  condition:                          # 可选，进一步条件
    type: "skill_used"
    in_game: true                     # 在本场对局中曾经使用过

# 回合开始/结束时
trigger:
  type: "on_turn_start" | "on_turn_end"

# 行动阶段开始时
trigger:
  type: "on_action_phase_start"

# 结束阶段
trigger:
  type: "on_end_phase"

# 投掷阶段
trigger:
  type: "on_roll_phase"

# 切换角色时
trigger:
  type: "on_character_switch"
  condition:
    type: "character_element_is"
    element: "pyro"

# 使用卡牌时
trigger:
  type: "on_card_play"
  condition:
    type: "card_type_is"
    card_type: "equipment"

# 卡牌加入手牌时
trigger:
  type: "on_card_added_to_hand"
  condition:
    type: "card_not_in_initial_deck"  # 名称不存在于初始牌组

# 触发元素反应时
trigger:
  type: "on_elemental_reaction"
  reaction_type: "vaporize" | "melt" | "overload" | ...

# 触发特定效果时（如"迸发扫描"、"飞云旗阵"）
trigger:
  type: "on_effect_triggered"
  effect_name: "迸发扫描"

# 准备技能时
trigger:
  type: "on_prepare_skill"
  count: 2                            # 可选，第几次准备技能

# 装备时（立即触发）
trigger:
  type: "on_equip"

# 召唤物/支援牌弃置时
trigger:
  type: "on_summon_discard" | "on_supporter_discard"
```

## 完整示例

### 示例 1：简单伤害技能

```yaml
skill:
  id: "khaenriahn_normal_attack"
  name: "普通攻击"
  type: "normal_attack"
  
  metadata:
    damage_type: "physical"
    base_damage: 2
    target_type: "active_character"
    cost_type: "dice"
    cost_value: 3
    
  cost:
    dices:
      any: 3
      
  effects:
    - type: "damage"
      value: 2
      element: "physical"
      target: "opponent_active_character"
```

### 示例 2：条件伤害技能

```yaml
skill:
  id: "skill_conditional_damage"
  name: "条件伤害"
  type: "elemental_skill"
  
  metadata:
    damage_type: "elemental"
    base_damage: 2
    target_type: "active_character"
    cost_type: "dice"
    cost_value: 3
    
  cost:
    dices:
      pyro: 3
      
  effects:
    - type: "if"
      condition:
        type: "hp_below"
        target: "opponent_active_character"
        threshold: 5
      then:
        - type: "damage"
          value: 4
          element: "pyro"
          target: "opponent_active_character"
      else:
        - type: "damage"
          value: 2
          element: "pyro"
          target: "opponent_active_character"
```

### 示例 3：复杂表达式技能

```yaml
skill:
  id: "skill_complex_damage"
  name: "复杂伤害计算"
  type: "elemental_burst"
  
  metadata:
    damage_type: "elemental"
    base_damage: 3
    target_type: "active_character"
    cost_type: "dice_energy"
    cost_value: 3
    
  cost:
    dices:
      pyro: 3
    energy: 2
    
  effects:
    - type: "damage"
      value:
        type: "expression"
        formula: "base_damage * (1 + status_bonus) + hp_bonus"
        variables:
          base_damage: 3
          status_bonus:
            type: "if"
            condition:
              type: "has_status"
              target: "self_active_character"
              status_type: "attack_boost"
            then:
              type: "function"
              name: "get_status_value"
              args:
                - "self_active_character"
                - "attack_boost"
            else: 0
          hp_bonus:
            type: "if"
            condition:
              type: "hp_below"
              target: "self_active_character"
              threshold: 5
            then: 2
            else: 0
      element: "pyro"
      target: "opponent_active_character"
```

### 示例 4：被动技能

```yaml
skill:
  id: "passive_fire_master"
  name: "火元素大师"
  type: "passive"
  
  metadata:
    trigger_type: "on_damage_dealt"
    effect_type: "damage_boost"
    
  trigger:
    type: "on_damage_dealt"
    condition:
      type: "and"
      conditions:
        - type: "element_is"
          target: "source"
          element: "pyro"
        - type: "damage_above"
          threshold: 2
  
  effects:
    - type: "damage"
      value: 1
      element: "pyro"
      target: "opponent_active_character"
```

### 示例 5：召唤物技能

```yaml
skill:
  id: "summon_fire_spirit"
  name: "召唤火灵"
  type: "elemental_skill"
  
  metadata:
    summon_type: "damage_dealer"
    duration: 2
    
  cost:
    dices:
      pyro: 3
      
  effects:
    - type: "summon"
      summon_id: "fire_spirit"
      duration: 2
      effects:
        - type: "passive"
          trigger:
            type: "on_turn_end"
          effects:
            - type: "damage"
              value: 1
              element: "pyro"
              target: "opponent_active_character"
```

### 示例 6：多效果组合技能

```yaml
skill:
  id: "skill_combo"
  name: "组合技能"
  type: "elemental_burst"
  
  metadata:
    damage_type: "elemental"
    base_damage: 3
    target_type: "all_characters"
    cost_type: "dice_energy"
    cost_value: 3
    
  cost:
    dices:
      pyro: 3
    energy: 2
    
  effects:
    - type: "sequence"
      effects:
        - type: "damage"
          value: 3
          element: "pyro"
          target: "opponent_active_character"
        
        - type: "if"
          condition:
            type: "hp_below"
            target: "opponent_active_character"
            threshold: 5
          then:
            - type: "damage"
              value: 2
              element: "pyro"
              target: "opponent_active_character"
        
        - type: "add_status"
          status_type: "attack_boost"
          value: 1
          duration: 2
          target: "self_active_character"
        
        - type: "draw_card"
          count: 1
```

## 技能特征编码

为了支持 RL 训练，需要将技能编码为数值特征向量。特征包括：

### 1. 元数据特征
- 技能类型（one-hot 编码）
- 元素类型（one-hot 编码）
- 目标类型（one-hot 编码）
- 消耗类型和数值

### 2. 效果摘要特征
- 总伤害值
- 总治疗值
- Buff/Debuff 数量
- 条件效果数量
- 序列效果数量

### 3. DSL 结构特征
- 最大嵌套深度
- 表达式复杂度
- 条件数量
- 循环次数

## 性能考虑

### 优化策略

1. **解析缓存**：技能配置解析后缓存，避免重复解析
2. **表达式预编译**：表达式编译为执行计划，提高执行效率
3. **条件短路求值**：AND/OR 条件遇到结果立即返回
4. **效果批量执行**：相同类型效果批量处理

## 配置验证

### 验证内容

1. **必需字段检查**：确保所有必需字段存在
2. **类型检查**：验证字段类型正确
3. **值范围检查**：验证数值在合理范围内
4. **引用检查**：验证引用的角色、卡牌等存在
5. **表达式语法检查**：验证表达式语法正确

## 总结

### 纯 DSL 方案的优势

1. ✅ **完全配置化**：所有逻辑都在配置文件中，无需修改代码
2. ✅ **易读易写**：声明式语法，比脚本更直观
3. ✅ **类型安全**：配置验证确保正确性
4. ✅ **特征提取**：DSL 结构便于提取特征用于 RL 训练
5. ✅ **无外部依赖**：不需要脚本引擎，减少依赖
6. ✅ **性能可控**：通过编译和缓存优化性能
7. ✅ **可扩展性**：支持插件式扩展，易于添加新效果类型
8. ✅ **完整覆盖**：基于实际卡牌数据分析，覆盖所有现有卡牌功能

### 支持的卡牌类型

- ✅ **角色技能**：普通攻击、元素战技、元素爆发、被动技能
- ✅ **装备牌**：天赋、武器、圣遗物
- ✅ **事件牌**：普通事件、料理、秘传、特技等
- ✅ **支援牌**：场地、角色支援等

### 支持的触发时机

- ✅ 投掷阶段、行动阶段、结束阶段
- ✅ 回合开始/结束
- ✅ 使用技能时/后
- ✅ 造成/受到伤害时
- ✅ 触发元素反应时
- ✅ 切换角色时
- ✅ 打出卡牌时
- ✅ 卡牌加入手牌时
- ✅ 装备时
- ✅ 准备技能时
- ✅ 触发特定效果时

### 支持的效果类型

- ✅ 伤害/治疗
- ✅ 状态添加/移除/修改
- ✅ 骰子操作（生成、调和、投掷、修改）
- ✅ 卡牌操作（抽牌、弃牌、加入手牌、窃取）
- ✅ 费用减免（技能、切换、卡牌）
- ✅ 伤害加成/减免
- ✅ 召唤物/支援牌
- ✅ 技能使用
- ✅ 角色操作（切换、复苏、最大生命值）
- ✅ 条件效果
- ✅ 随机选择
- ✅ 穿透伤害

### 设计原则

1. **向后兼容**：新版本 DSL 保持对旧版本配置的兼容性
2. **渐进增强**：核心功能稳定，扩展功能可选
3. **明确语义**：每个效果类型都有明确的语义和用途
4. **组合能力**：通过组合基础效果实现复杂逻辑
5. **性能优先**：设计时考虑执行效率，支持预编译和缓存

该方案可以满足所有现有卡牌需求，包括被动技能和复杂触发条件，同时保持配置的简洁性和可维护性，并为未来新卡牌类型和效果提供了良好的扩展基础。

## 实际卡牌示例

基于 `data/` 目录中的卡牌数据，以下是一些实际卡牌的 DSL 配置示例：

### 示例 7：天赋装备牌 - 猫爪冰摇

```yaml
card:
  id: 211021
  name: "猫爪冰摇"
  type: "equipment"
  subtype: "talent"
  
  cost:
    dices:
      any: 3
      matching: 3
  
  restrictions:
    deck_requirement:
      character_id: "character_1102"  # 迪奥娜
  
  equip_condition:
    character_id: "character_1102"
    active_character: true
  
  on_equip:
    - type: "use_skill"
      skill_name: "猫爪冻冻"
  
  effects:
    # 持续效果：猫爪护盾提供的护盾值+1
    - type: "modify_status"
      status_type: "shield_value"
      operation: "add"
      value: 1
      target: "self_active_character"
      condition:
        type: "has_status"
        status_type: "cat_paw_shield"
```

### 示例 8：天赋装备牌 - 冷血之剑

```yaml
card:
  id: 211031
  name: "冷血之剑"
  type: "equipment"
  subtype: "talent"
  
  cost:
    dices:
      any: 3
      matching: 3
  
  restrictions:
    deck_requirement:
      character_id: "character_1103"  # 凯亚
  
  equip_condition:
    character_id: "character_1103"
    active_character: true
  
  on_equip:
    - type: "use_skill"
      skill_name: "霜袭"
  
  trigger:
    type: "on_specific_skill_use"
    skill_name: "霜袭"
    limit:
      per_turn: 1
  
  effects:
    - type: "heal"
      value: 2
      target: "self_active_character"
```

### 示例 9：武器装备牌 - 祭礼剑

```yaml
card:
  id: 311502
  name: "祭礼剑"
  type: "equipment"
  subtype: "weapon"
  
  cost:
    dices:
      any: 3
      same_color: true
  
  equip_condition:
    character_type: "sword"
  
  effects:
    # 持续效果：角色造成的伤害+1
    - type: "damage_boost"
      skill_type: "all"
      value: 1
      target: "self_active_character"
  
  trigger:
    type: "on_skill_use"
    condition:
      type: "skill_type_is"
      skill_type: "elemental_skill"
    limit:
      per_turn: 1
  
  effects:
    # 触发效果：生成1个此角色类型的元素骰
    - type: "add_dice"
      element: "character_element"
      count: 1
```

### 示例 10：支援牌 - 群玉阁

```yaml
card:
  id: 321003
  name: "群玉阁"
  type: "support"
  subtype: "location"
  
  cost:
    dices:
      any: 0
  
  trigger:
    type: "on_roll_phase"
  
  effects:
    # 投掷阶段：2个元素骰初始总是投出我方出战角色类型的元素
    - type: "dice_roll_modifier"
      phase: "roll_phase"
      effect: "guarantee_elements"
      count: 2
      element: "character_element"
  
  trigger:
    type: "on_action_phase_start"
    condition:
      type: "hand_size_below"
      side: "self"
      threshold: 3
  
  effects:
    # 行动阶段开始时：如果手牌数量不多于3，则弃置此牌，生成1个万能元素
    - type: "remove_supporter"
      supporter_id: "qunyu_ge"
    - type: "add_dice"
      element: "omni"
      count: 1
```

### 示例 11：事件牌 - 最好的伙伴

```yaml
card:
  id: 332001
  name: "最好的伙伴！"
  type: "event"
  
  cost:
    dices:
      any: 2
  
  effects:
    - type: "add_dice"
      element: "omni"
      count: 2
```

### 示例 12：料理事件牌 - 仙跳墙

```yaml
card:
  id: 333002
  name: "仙跳墙"
  type: "event"
  subtype: "food"
  
  cost:
    dices:
      any: 2
  
  restrictions:
    play_limit:
      per_character: 1  # 每回合每个角色最多食用1次料理
  
  effects:
    # 本回合中，目标角色下一次元素爆发造成的伤害+3
    - type: "damage_boost"
      skill_type: "elemental_burst"
      value: 3
      duration: 1
      count: 1
      target: "target_character"
```

### 示例 13：天赋装备牌 - 唯此一心

```yaml
card:
  id: 211011
  name: "唯此一心"
  type: "equipment"
  subtype: "talent"
  
  cost:
    dices:
      any: 5
      matching: 5
  
  restrictions:
    deck_requirement:
      character_id: "character_1101"  # 甘雨
  
  equip_condition:
    character_id: "character_1101"
    active_character: true
  
  on_equip:
    - type: "use_skill"
      skill_name: "霜华矢"
  
  trigger:
    type: "on_specific_skill_use"
    skill_name: "霜华矢"
    condition:
      type: "skill_used"
      skill_name: "霜华矢"
      in_game: true
  
  effects:
    # 如果此技能在本场对局中曾经被使用过，则其对敌方后台角色造成的穿透伤害改为3点
    - type: "modify_skill_effect"
      skill_name: "霜华矢"
      effect_type: "piercing_damage"
      value: 3
      target: "all_opponent_backend_characters"
```

### 示例 14：天赋装备牌 - 预算师的技艺

```yaml
card:
  id: 217081
  name: "预算师的技艺"
  type: "equipment"
  subtype: "talent"
  
  cost:
    dices:
      any: 3
      matching: 3
  
  restrictions:
    deck_requirement:
      character_id: "character_1708"  # 卡维
  
  equip_condition:
    character_id: "character_1708"
    active_character: true
  
  on_equip:
    - type: "use_skill"
      skill_name: "画则巧施"
  
  trigger:
    type: "on_effect_triggered"
    effect_name: "迸发扫描"
    limit:
      per_turn: 1
  
  effects:
    # 将1张所舍弃卡牌的复制加入你的手牌
    - type: "add_card_to_hand"
      from_discard: true
      count: 1
    # 如果该牌为场地牌，则使本回合中我方下次打出场地时少花费2个元素骰
    - type: "conditional_effect"
      condition:
        type: "card_type_is"
        card_type: "support"
        card_subtype: "location"
      then:
        - type: "reduce_card_cost"
          card_subtype: "location"
          reduction: 2
          duration: 1
          count: 1
```

### 示例 15：天赋装备牌 - 庄谐并举

```yaml
card:
  id: 216071
  name: "庄谐并举"
  type: "equipment"
  subtype: "talent"
  
  cost:
    dices:
      any: 3
      matching: 3
    energy: 2
  
  restrictions:
    deck_requirement:
      character_id: "character_1607"  # 云堇
  
  equip_condition:
    character_id: "character_1607"
    active_character: true
  
  on_equip:
    - type: "use_skill"
      skill_name: "破嶂见旌仪"
  
  trigger:
    type: "on_effect_triggered"
    effect_name: "飞云旗阵"
    condition:
      type: "hand_size_equal"
      side: "self"
      threshold: 0
  
  effects:
    # 如果我方没有手牌，则使此次技能伤害+2
    - type: "damage_boost"
      skill_type: "all"
      value: 2
      duration: 0  # 仅本次生效
      target: "self_active_character"
```

### 示例 16：事件牌 - 旧时庭园（秘传）

```yaml
card:
  id: 330001
  name: "旧时庭园"
  type: "event"
  subtype: "secret"
  
  cost:
    dices:
      any: 0
  
  restrictions:
    play_limit:
      per_game: 1  # 整局游戏只能打出一张秘传
    condition:
      type: "has_equipment"
      target: "all_self_characters"
      equipment_type: "weapon"
      or:
        type: "has_equipment"
        target: "all_self_characters"
        equipment_type: "artifact"
  
  effects:
    # 本回合中，我方下次打出武器或圣遗物装备牌时少花费2个元素骰
    - type: "reduce_card_cost"
      card_type: "equipment"
      card_subtype: ["weapon", "artifact"]
      reduction: 2
      duration: 1
      count: 1
```

### 示例 17：事件牌 - 子弹的戏法

```yaml
card:
  id: 215111
  name: "子弹的戏法"
  type: "event"
  subtype: "talent"
  
  cost:
    dices:
      any: 1
  
  restrictions:
    deck_requirement:
      character_id: "character_1511"  # 恰斯卡
  
  condition:
    type: "has_character"
    character_id: "character_1511"
    side: "self"
  
  effects:
    # 将一张追影弹加入手牌
    - type: "add_card_to_hand"
      card_id: "card_追影弹"
      count: 1
```

### 示例 18：天赋装备牌 - 饕噬尽吞

```yaml
card:
  id: 227041
  name: "饕噬尽吞"
  type: "equipment"
  subtype: "talent"
  
  cost:
    dices:
      any: 1
  
  restrictions:
    deck_requirement:
      character_id: "character_2704"  # 贪食匿叶龙山王
  
  equip_condition:
    character_id: "character_2704"
    active_character: true
  
  effects:
    # 装备时：敌方抓1张牌，然后我方窃取1张原本元素骰费用最高的对方手牌
    - type: "draw_card"
      side: "opponent"
      count: 1
    - type: "steal_card"
      filter:
        cost_highest: true
      count: 1
  
  trigger:
    type: "on_card_added_to_hand"
    condition:
      type: "card_not_in_initial_deck"
    limit:
      per_turn: 1
  
  effects:
    # 我方打出名称不存在于本局最初牌组的牌时：触发贪食之王1次
    - type: "trigger_effect"
      effect_name: "贪食之王"
      count: 1
```

## DSL 扩展性设计

为了支持未来可能出现的新卡牌类型和效果，DSL 设计采用了以下扩展性策略：

### 1. 插件式效果系统

```yaml
# 自定义效果类型可以通过扩展点添加
- type: "custom"
  effect_id: "custom_effect_001"
  parameters:
    param1: value1
    param2: value2
```

### 2. 条件表达式扩展

```yaml
# 支持自定义条件检查
condition:
  type: "custom"
  condition_id: "custom_condition_001"
  parameters:
    param1: value1
```

### 3. 触发器扩展

```yaml
# 支持自定义触发器
trigger:
  type: "custom"
  trigger_id: "custom_trigger_001"
  parameters:
    param1: value1
```

### 4. 元数据扩展

```yaml
# 元数据字段可以自由扩展
metadata:
  custom_field1: value1
  custom_field2: value2
```

### 5. 版本控制

```yaml
# 支持 DSL 版本管理
dsl_version: "1.0"
compatibility:
  min_version: "1.0"
  max_version: "2.0"
```

## 实现建议

1. **分层设计**：
   - 核心层：基础效果、条件、触发器
   - 扩展层：卡牌特定效果、自定义逻辑
   - 应用层：游戏规则、状态管理

2. **验证机制**：
   - 静态验证：配置加载时验证
   - 运行时验证：执行时检查条件

3. **性能优化**：
   - 效果预编译：将 DSL 编译为执行计划
   - 条件缓存：缓存条件检查结果
   - 触发器索引：建立触发器索引加速查找

4. **调试支持**：
   - 效果追踪：记录每个效果的执行
   - 条件日志：记录条件检查过程
   - 可视化工具：图形化展示卡牌效果流程
