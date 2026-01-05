# 技能效果系统设计

## 概述

技能效果系统用于处理角色的特殊技能效果，如计数效果、元素附着、伤害修改等。系统采用事件驱动和 Hook 机制，支持灵活的效果组合和扩展。

**注意**：本系统与 [目标与动作系统](target_action_system.md) 紧密集成。技能效果可以触发动作，动作执行时包含完整的上下文信息（伤害来源、目标等）。

## 设计原则

1. **可组合性**：效果可以组合使用，支持多个效果同时生效
2. **可扩展性**：易于添加新的效果类型
3. **声明式配置**：效果可以通过 YAML 配置文件定义
4. **事件驱动**：效果通过事件系统触发，与游戏流程解耦
5. **状态管理**：效果相关的状态统一管理
6. **上下文完整性**：效果执行时包含完整的上下文信息（来源、目标、触发条件等）

## 效果类型

### 1. 计数效果（Counter Effect）

用于记录技能使用次数，并根据次数触发不同效果。

**示例**：
- "第三次使用该技能时威力 +2"
- "每使用一次，下次使用时伤害 +1"

**实现方式**：
- 在角色或技能上维护计数器
- 在技能使用前检查计数，触发相应效果

### 2. 元素附着效果（Elemental Application Effect）

对目标或自己附着元素，用于触发元素反应。

**示例**：
- "使用后对敌人附着水元素"
- "使用后对自己附着水元素"

**实现方式**：
- 使用 `ElementalApplicationAction` 动作
- 支持单个目标或群体目标
- 在技能使用后通过动作系统执行

### 3. 伤害修改效果（Damage Modification Effect）

修改技能的伤害数值或类型。

**示例**：
- "伤害 +2"
- "伤害 × 1.5"
- "伤害类型改为火元素"

**实现方式**：
- 在伤害计算时通过 Hook 修改伤害值
- 支持加值、乘值、替换等多种修改方式

### 4. 状态添加效果（Status Application Effect）

为目标添加状态效果（Buff/Debuff）。

**示例**：
- "对敌人添加 2 回合的冻结状态"
- "对自己添加 1 回合的护盾"

**实现方式**：
- 创建状态添加事件
- 状态系统管理状态的持续时间和效果

### 5. 条件效果（Conditional Effect）

根据条件触发效果。

**示例**：
- "如果敌人有火元素附着，伤害 +1"
- "如果自己生命值低于 50%，伤害 +2"

**实现方式**：
- 效果包含条件检查函数
- 在触发时检查条件，满足则执行

### 6. 费用修改效果（Cost Modification Effect）

修改技能的费用需求。

**示例**：
- "如果手牌数 ≥ 5，费用 -1"
- "第一次使用费用为 0"

**实现方式**：
- 在费用检查时通过 Hook 修改费用
- 支持费用减免和增加

## 效果触发时机

效果可以在以下时机触发：

1. **Before Use**：技能使用前
   - 用于费用修改、条件检查等

2. **On Use**：技能使用时
   - 用于计数更新、状态检查等

3. **After Use**：技能使用后
   - 用于元素附着、状态添加等

4. **On Damage Calculation**：伤害计算时
   - 用于伤害修改

5. **On Skill Event**：技能事件触发时
   - 用于通用效果触发

## 架构设计

### 效果基类

```python
class SkillEffect:
    """技能效果基类"""
    
    def __init__(self, effect_type: str, trigger_timing: str):
        self.effect_type = effect_type
        self.trigger_timing = trigger_timing
    
    def can_trigger(self, state: State, context: EffectContext) -> bool:
        """检查效果是否可以触发"""
        raise NotImplementedError
    
    def apply(self, state: State, context: EffectContext, 
              event_queue: MutableSequence[BaseEvent]) -> None:
        """应用效果"""
        raise NotImplementedError
```

### 效果上下文

效果上下文基于动作上下文（ActionContext），包含完整的执行信息：

```python
@dataclass
class EffectContext:
    """效果执行上下文（基于 ActionContext）"""
    # 来源信息
    source: CharacterID              # 动作来源角色
    source_side: int                 # 来源方（0 或 1）
    skill: Optional[BaseSkill] = None  # 使用的技能（如果有）
    skill_name: Optional[str] = None   # 技能名称
    
    # 触发信息
    trigger_event: Optional[BaseEvent] = None  # 触发事件
    trigger_type: Optional[str] = None        # 触发类型
    
    # 伤害相关（如果是伤害动作）
    damage_source: Optional[CharacterID] = None  # 伤害来源
    damage_element: Optional[DamageElement] = None  # 伤害元素
    damage_value: Optional[int] = None  # 伤害数值
    damage_target: Optional[CharacterID] = None  # 伤害目标
    
    # 目标信息
    target: Optional[CharacterID] = None
    targets: Optional[List[CharacterID]] = None  # 多个目标
    
    # 其他上下文
    custom_data: Dict[str, Any] = field(default_factory=dict)  # 自定义数据
```

**注意**：详细的上下文定义请参考 [目标与动作系统文档](target_action_system.md#动作上下文action-context)。

### 效果注册系统

```python
class EffectRegistry:
    """效果注册表"""
    
    def __init__(self):
        self.effects: Dict[str, Type[SkillEffect]] = {}
    
    def register(self, name: str, effect_class: Type[SkillEffect]):
        """注册效果类型"""
        self.effects[name] = effect_class
    
    def create_effect(self, effect_data: Dict) -> SkillEffect:
        """从配置创建效果实例"""
        effect_type = effect_data["type"]
        effect_class = self.effects[effect_type]
        return effect_class.from_config(effect_data)
```

### 技能效果管理

```python
class SkillWithEffects(BaseSkill):
    """带效果的技能"""
    
    def __init__(self, base_skill: BaseSkill, effects: List[SkillEffect]):
        super().__init__(...)
        self.base_skill = base_skill
        self.effects = effects
    
    def apply(self, state: State, event_queue: MutableSequence[BaseEvent]) -> None:
        context = EffectContext(...)
        
        # 触发 Before Use 效果
        self._trigger_effects("before_use", state, context, event_queue)
        
        # 执行基础技能
        self.base_skill.apply(state, event_queue)
        
        # 触发 On Use 效果
        self._trigger_effects("on_use", state, context, event_queue)
        
        # 触发 After Use 效果
        self._trigger_effects("after_use", state, context, event_queue)
    
    def _trigger_effects(self, timing: str, state: State, 
                        context: EffectContext,
                        event_queue: MutableSequence[BaseEvent]):
        for effect in self.effects:
            if effect.trigger_timing == timing and effect.can_trigger(state, context):
                effect.apply(state, context, event_queue)
```

## 状态管理

### 角色状态扩展

```python
class Character:
    def __init__(self, ...):
        # ... 现有属性
        self.skill_counters: Dict[str, int] = {}  # 技能使用计数
        self.effects: List[SkillEffect] = []  # 角色级别的效果
```

### 技能状态

```python
class SkillState:
    """技能状态，用于存储技能相关的状态"""
    def __init__(self, skill_name: str):
        self.skill_name = skill_name
        self.use_count = 0
        self.custom_data: Dict[str, Any] = {}
```

## 配置格式

### YAML 配置示例

```yaml
skills:
  - name: 普通攻击
    type: normal_attack
    damage_element: Physical
    damage_count: 2
    cost:
      element: Pyro
      element_count: 1
      any_count: 2
    effects:
      # 计数效果：第三次使用时伤害 +2
      - type: counter_damage_boost
        trigger_timing: on_damage_calculation
        counter_key: "normal_attack_count"
        threshold: 3
        damage_bonus: 2
      
      # 元素附着效果：使用后对敌人附着水元素
      - type: elemental_application
        trigger_timing: after_use
        target: enemy
        element: Hydro
      
      # 条件效果：如果敌人有火元素附着，伤害 +1
      - type: conditional_damage_boost
        trigger_timing: on_damage_calculation
        condition:
          type: enemy_has_element
          element: Pyro
        damage_bonus: 1
```

## 具体效果实现示例

### 1. 计数伤害加成效果

```python
class CounterDamageBoostEffect(SkillEffect):
    """计数伤害加成效果"""
    
    def __init__(self, counter_key: str, threshold: int, damage_bonus: int):
        super().__init__("counter_damage_boost", "on_damage_calculation")
        self.counter_key = counter_key
        self.threshold = threshold
        self.damage_bonus = damage_bonus
    
    def can_trigger(self, state: State, context: EffectContext) -> bool:
        character = context.character
        count = character.skill_counters.get(self.counter_key, 0)
        return count >= self.threshold
    
    def apply(self, state: State, context: EffectContext,
              event_queue: MutableSequence[BaseEvent]) -> None:
        if context.damage_event:
            context.damage_event.value += self.damage_bonus
```

### 2. 元素附着效果

```python
class ElementalApplicationEffect(SkillEffect):
    """元素附着效果（使用动作系统）"""
    
    def __init__(self, target: TargetType, element: Element):
        super().__init__("elemental_application", "after_use")
        self.target = target
        self.element = element
    
    def apply(self, state: State, context: EffectContext,
              event_queue: MutableSequence[BaseEvent]) -> None:
        from .action import ElementalApplicationAction
        
        action = ElementalApplicationAction(self.target, self.element)
        action.execute(state, context, event_queue)
```

### 3. 条件伤害加成效果

```python
class ConditionalDamageBoostEffect(SkillEffect):
    """条件伤害加成效果"""
    
    def __init__(self, condition: Dict, damage_bonus: int):
        super().__init__("conditional_damage_boost", "on_damage_calculation")
        self.condition = condition
        self.damage_bonus = damage_bonus
    
    def can_trigger(self, state: State, context: EffectContext) -> bool:
        condition_type = self.condition["type"]
        
        if condition_type == "enemy_has_element":
            element = Element[self.condition["element"]]
            # 检查敌人是否有该元素附着
            return self._check_enemy_element(context.target, element)
        
        return False
    
    def apply(self, state: State, context: EffectContext,
              event_queue: MutableSequence[BaseEvent]) -> None:
        if context.damage_event:
            context.damage_event.value += self.damage_bonus
```

## Hook 系统集成

效果系统与 Hook 系统集成，支持在事件处理过程中修改：

```python
class DamageCalculationHook:
    """伤害计算 Hook"""
    
    def __init__(self, effect: SkillEffect):
        self.effect = effect
    
    def on_damage_calculation(self, damage_event: DamageEvent, 
                              state: State, context: EffectContext):
        if self.effect.can_trigger(state, context):
            self.effect.apply(state, context, [])
```

## 实现步骤

### 阶段 1：基础框架
1. 实现 `SkillEffect` 基类
2. 实现 `EffectContext` 数据类
3. 实现 `EffectRegistry` 注册系统
4. 扩展 `BaseSkill` 支持效果列表

### 阶段 2：核心效果
1. 实现计数效果
2. 实现元素附着效果
3. 实现伤害修改效果

### 阶段 3：高级效果
1. 实现条件效果
2. 实现状态添加效果
3. 实现费用修改效果

### 阶段 4：配置支持
1. 实现 YAML 配置解析
2. 实现效果从配置创建
3. 更新角色加载器支持效果

### 阶段 5：测试和优化
1. 编写单元测试
2. 性能优化
3. 文档完善

## 注意事项

1. **性能考虑**：效果检查可能频繁执行，需要优化
2. **状态同步**：确保效果状态与游戏状态同步
3. **效果顺序**：多个效果的执行顺序需要明确定义
4. **错误处理**：效果执行失败不应影响游戏流程
5. **可测试性**：效果应该易于单独测试

## 与目标动作系统集成

技能效果系统与目标动作系统紧密集成：

1. **效果可以触发动作**：效果执行时可以创建并执行动作
2. **动作包含完整上下文**：动作执行时包含伤害来源、目标等完整信息
3. **支持复杂组合**：效果 + 动作 + 目标可以组合出复杂的行为

**示例**：受到攻击时反击

```python
class OnDamageTakenCounterEffect(SkillEffect):
    """受到攻击时反击"""
    
    def __init__(self, counter_action: BaseAction):
        super().__init__("on_damage_taken_counter", "on_damage_taken")
        self.counter_action = counter_action
    
    def can_trigger(self, state: State, context: EffectContext) -> bool:
        # 检查是否是受到伤害
        if isinstance(context.trigger_event, DamageEvent):
            # 检查是否是自己受到伤害
            return context.damage_target == context.source
    
    def apply(self, state: State, context: EffectContext,
              event_queue: MutableSequence[BaseEvent]) -> None:
        # 创建反击动作的上下文
        counter_context = ActionContext(
            source=context.source,
            source_side=context.source_side,
            trigger_event=context.trigger_event,
            trigger_type="on_damage_taken",
            damage_source=context.damage_source  # 反击伤害来源
        )
        # 执行反击动作
        self.counter_action.execute(state, counter_context, event_queue)
```

详细的目标与动作系统设计请参考 [目标与动作系统文档](target_action_system.md)。

## 扩展性

系统设计支持未来扩展：
- 新的效果类型只需实现 `SkillEffect` 接口
- 新的触发时机可以添加到枚举中
- 效果可以组合使用，支持复杂逻辑
- 可以通过 Hook 系统与其他系统集成
- 可以与目标动作系统组合，实现复杂行为

