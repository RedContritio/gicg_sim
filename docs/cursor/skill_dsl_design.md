# 技能 DSL 设计文档

## 设计理念

采用**纯 DSL（领域特定语言）方案**，所有技能逻辑（包括主动技能、被动技能、触发条件等）都通过 YAML 配置文件描述，不使用任何脚本语言。

### 核心原则

1. **完全配置化**：所有技能逻辑都在配置文件中
2. **声明式语法**：易读、易写、易维护
3. **功能完整**：支持条件、表达式、循环等复杂逻辑
4. **类型安全**：配置验证确保正确性
5. **特征提取**：DSL 结构便于提取特征用于 RL 训练

## DSL 语法

### 技能基础结构

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
  effects:                           # 召唤物效果
    - type: "damage"
      value: 1
      trigger: "on_turn_end"

# 支援牌
- type: "add_supporter"
  supporter_id: "supporter_liyue"
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
  type: "hand_size_below" | "hand_size_above"
  side: "self" | "opponent"
  threshold: 5

# 骰子条件
condition:
  type: "dice_count_below" | "dice_count_above"
  side: "self"
  element: "pyro" | null              # null 表示任意元素
  threshold: 3

# 组合条件
condition:
  type: "and" | "or"
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

- **数学函数**：`min(a, b)`, `max(a, b)`, `abs(x)`, `floor(x)`, `ceil(x)`
- **游戏函数**：`get_hp(target)`, `get_max_hp(target)`, `get_energy(target)`, `get_max_energy(target)`, `get_status_value(target, status_type)`, `count_cards(side, filter)`, `count_dices(side, element)`, `count_characters(side)`

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

# 回合开始/结束时
trigger:
  type: "on_turn_start" | "on_turn_end"

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

纯 DSL 方案的优势：

1. ✅ **完全配置化**：所有逻辑都在配置文件中，无需修改代码
2. ✅ **易读易写**：声明式语法，比脚本更直观
3. ✅ **类型安全**：配置验证确保正确性
4. ✅ **特征提取**：DSL 结构便于提取特征用于 RL 训练
5. ✅ **无外部依赖**：不需要脚本引擎，减少依赖
6. ✅ **性能可控**：通过编译和缓存优化性能

该方案可以满足所有技能需求，包括被动技能和复杂触发条件，同时保持配置的简洁性和可维护性。
