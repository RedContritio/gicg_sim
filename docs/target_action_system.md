# 目标与动作系统设计

## 概述

目标与动作系统（Target × Action System）是游戏核心机制之一，用于定义技能、效果等对游戏实体的操作。系统采用组合式设计，支持灵活的目标选择和多样化的动作类型。

## 设计原则

1. **组合性**：目标与动作可以自由组合，形成丰富的效果
2. **可扩展性**：易于添加新的目标类型和动作类型
3. **上下文完整性**：动作执行时包含完整的上下文信息（来源、目标、触发条件等）
4. **统一接口**：所有动作遵循统一的接口规范
5. **事件驱动**：动作通过事件系统执行，支持 Hook 拦截和修改

## 目标系统（Target System）

### 目标描述类型

目标描述定义了对哪些实体进行操作：

```python
class TargetDescType(Enum):
    # 基础目标
    active = "active"              # 站场角色
    active_next = "active_next"    # 下一个站场角色
    active_prev = "active_prev"    # 上一个站场角色
    inactive = "inactive"          # 所有非站场角色
    
    # 直接选择
    selected = "selected"          # 选中的角色（需要额外指定）
    
    # 特殊规则
    all = "all"                    # 所有角色
    all_active = "all_active"      # 所有站场角色
    all_inactive = "all_inactive"  # 所有非站场角色
    none = "none"                  # 无目标
    
    # 相对位置
    self = "self"                  # 自己
    source = "source"              # 动作来源（技能使用者）
    target = "target"              # 当前目标
    
    # 相邻角色
    adjacent = "adjacent"          # 相邻角色（站场角色的前一个和后一个）
    adjacent_next = "adjacent_next"  # 下一个相邻角色
    adjacent_prev = "adjacent_prev"  # 上一个相邻角色
```

### 目标方（Side）

定义目标属于哪一方：

```python
class SideDescType(Enum):
    mine = "mine"        # 己方
    enemy = "enemy"      # 敌方
    both = "both"       # 双方
```

### 目标类型

```python
class TargetType:
    """目标类型，组合目标描述和所属方"""
    
    def __init__(self, 
                 target: TargetDescType,
                 side: SideDescType = SideDescType.enemy,
                 specific_id: Optional[CharacterID] = None):
        self.target = target
        self.side = side
        self.specific_id = specific_id  # 用于 selected 类型
    
    def resolve(self, state: State, source: CharacterID) -> List[CharacterID]:
        """解析目标，返回实际的角色 ID 列表"""
        # 实现目标解析逻辑
        pass
```

### 目标解析

目标解析器负责将目标描述转换为实际的角色列表：

```python
class TargetResolver:
    """目标解析器"""
    
    @staticmethod
    def resolve(target: TargetType, 
                state: State, 
                source_side: int,
                source_character: CharacterID) -> List[CharacterID]:
        """解析目标为角色 ID 列表"""
        # 根据 target.target 和 target.side 解析目标
        # 返回 CharacterID 列表
        pass
```

## 动作系统（Action System）

### 动作类型

动作定义了对目标执行什么操作：

```python
class ActionType(Enum):
    # 伤害类
    damage = "damage"                    # 造成伤害
    damage_aoe = "damage_aoe"            # 群体伤害
    damage_chain = "damage_chain"        # 连锁伤害（攻击下一个人）
    
    # 治疗类
    heal = "heal"                        # 治疗
    heal_aoe = "heal_aoe"               # 群体治疗
    heal_chain = "heal_chain"           # 连锁治疗（治疗下一个人）
    
    # 元素类
    apply_element = "apply_element"     # 附着元素
    remove_element = "remove_element"   # 移除元素
    
    # 状态类
    add_status = "add_status"           # 添加状态
    remove_status = "remove_status"     # 移除状态
    
    # 能量类
    gain_energy = "gain_energy"         # 获得能量
    consume_energy = "consume_energy"  # 消耗能量
    
    # 切换类
    switch_character = "switch_character"  # 切换角色
    
    # 其他
    draw_card = "draw_card"            # 抽牌
    discard_card = "discard_card"      # 弃牌
    modify_cost = "modify_cost"        # 修改费用
```

### 动作基类

```python
class BaseAction:
    """动作基类"""
    
    def __init__(self, action_type: ActionType, target: TargetType):
        self.action_type = action_type
        self.target = target
    
    def execute(self, 
                state: State,
                context: ActionContext,
                event_queue: MutableSequence[BaseEvent]) -> None:
        """执行动作"""
        raise NotImplementedError
    
    def can_execute(self, state: State, context: ActionContext) -> bool:
        """检查动作是否可以执行"""
        return True
```

### 具体动作实现

#### 伤害动作

```python
class DamageAction(BaseAction):
    """伤害动作"""
    
    def __init__(self, 
                 target: TargetType,
                 element: DamageElement,
                 value: int,
                 is_aoe: bool = False,
                 chain: bool = False):
        action_type = ActionType.damage_aoe if is_aoe else (
            ActionType.damage_chain if chain else ActionType.damage
        )
        super().__init__(action_type, target)
        self.element = element
        self.value = value
        self.is_aoe = is_aoe
        self.chain = chain
    
    def execute(self, state: State, context: ActionContext,
                event_queue: MutableSequence[BaseEvent]) -> None:
        from .event.damage import DamageEvent
        
        # 解析目标
        targets = TargetResolver.resolve(
            self.target, state, context.source_side, context.source
        )
        
        # 对每个目标造成伤害
        for target_id in targets:
            damage_event = DamageEvent(
                source=context.source,
                target=TargetType(TargetDescType.selected, 
                                SideDescType.enemy, target_id),
                element=self.element,
                value=self.value,
                context=context  # 包含完整上下文
            )
            event_queue.append(damage_event)
            
            # 如果是连锁伤害，继续攻击下一个
            if self.chain and target_id != targets[-1]:
                # 找到下一个目标并继续
                pass
```

#### 治疗动作

```python
class HealAction(BaseAction):
    """治疗动作"""
    
    def __init__(self,
                 target: TargetType,
                 value: int,
                 is_aoe: bool = False,
                 chain: bool = False):
        action_type = ActionType.heal_aoe if is_aoe else (
            ActionType.heal_chain if chain else ActionType.heal
        )
        super().__init__(action_type, target)
        self.value = value
        self.is_aoe = is_aoe
        self.chain = chain
    
    def execute(self, state: State, context: ActionContext,
                event_queue: MutableSequence[BaseEvent]) -> None:
        from .event.heal import HealEvent
        
        targets = TargetResolver.resolve(
            self.target, state, context.source_side, context.source
        )
        
        for target_id in targets:
            heal_event = HealEvent(
                source=context.source,
                target=target_id,
                value=self.value,
                context=context
            )
            event_queue.append(heal_event)
```

## 动作上下文（Action Context）

动作上下文包含执行动作所需的所有信息：

```python
@dataclass
class ActionContext:
    """动作执行上下文"""
    
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
    
    # 其他上下文
    custom_data: Dict[str, Any] = field(default_factory=dict)  # 自定义数据
```

## 增强的事件系统

### 伤害事件增强

```python
class DamageEvent(BaseEvent):
    """伤害事件（增强版）"""
    
    def __init__(self,
                 source: CharacterID,
                 target: TargetType,
                 element: DamageElement,
                 value: int,
                 context: Optional[ActionContext] = None,
                 is_piercing: bool = False,
                 can_modify: bool = True):
        self.source = source
        self.target = target
        self.element = element
        self.value = value
        self.context = context  # 完整上下文
        self.is_piercing = is_piercing
        self.can_modify = can_modify  # 是否可以被修改
        self.modifiers: List[DamageModifier] = []  # 伤害修改器
```

### 治疗事件

```python
class HealEvent(BaseEvent):
    """治疗事件"""
    
    def __init__(self,
                 source: CharacterID,
                 target: CharacterID,
                 value: int,
                 context: Optional[ActionContext] = None):
        self.source = source
        self.target = target
        self.value = value
        self.context = context
```

### 元素附着事件

```python
class ElementalApplicationEvent(BaseEvent):
    """元素附着事件"""
    
    def __init__(self,
                 source: CharacterID,
                 target: CharacterID,
                 element: Element,
                 context: Optional[ActionContext] = None):
        self.source = source
        self.target = target
        self.element = element
        self.context = context
```

## 技能与动作的集成

### 技能动作定义

技能可以定义多个动作：

```python
class BaseSkill:
    def __init__(self, ...):
        # ... 现有属性
        self.actions: List[BaseAction] = []  # 动作列表
    
    def apply(self, state: State, event_queue: MutableSequence[BaseEvent]) -> None:
        # 创建动作上下文
        context = ActionContext(
            source=state.current_character,
            source_side=state.current_side,
            skill=self,
            skill_name=self.name
        )
        
        # 执行费用检查
        event_queue.append(CostEvent(self.cost))
        
        # 执行所有动作
        for action in self.actions:
            if action.can_execute(state, context):
                action.execute(state, context, event_queue)
```

### YAML 配置示例

```yaml
skills:
  - name: 普通攻击
    type: normal_attack
    cost:
      element: Pyro
      element_count: 1
      any_count: 2
    actions:
      # 基础伤害
      - type: damage
        target:
          target: active
          side: enemy
        element: Physical
        value: 2
      
      # 对下一个角色造成伤害（连锁）
      - type: damage_chain
        target:
          target: active_next
          side: enemy
        element: Physical
        value: 1
  
  - name: 元素战技
    type: elemental_skill
    cost:
      element: Hydro
      element_count: 3
    actions:
      # 群体伤害
      - type: damage_aoe
        target:
          target: all_active
          side: enemy
        element: Hydro
        value: 1
      
      # 附着水元素
      - type: apply_element
        target:
          target: active
          side: enemy
        element: Hydro
  
  - name: 治疗技能
    type: elemental_skill
    cost:
      element: Dendro
      element_count: 2
    actions:
      # 治疗自己
      - type: heal
        target:
          target: self
          side: mine
        value: 2
      
      # 治疗下一个角色
      - type: heal_chain
        target:
          target: active_next
          side: mine
        value: 1
```

## 效果系统集成

效果系统可以与动作系统集成，支持在动作执行前后触发效果：

```python
class SkillEffect:
    def apply(self, state: State, context: ActionContext,
              event_queue: MutableSequence[BaseEvent]) -> None:
        # 效果可以访问完整的动作上下文
        # 包括伤害来源、目标、触发条件等
        pass
```

### 效果示例：受到攻击时触发

```python
class OnDamageTakenEffect(SkillEffect):
    """受到攻击时触发的效果"""
    
    def __init__(self, trigger_action: BaseAction):
        super().__init__("on_damage_taken", "on_damage_taken")
        self.trigger_action = trigger_action
    
    def can_trigger(self, state: State, context: ActionContext) -> bool:
        # 检查是否是受到伤害
        if isinstance(context.trigger_event, DamageEvent):
            # 检查是否是自己受到伤害
            return context.trigger_event.target.specific_id == context.source
        return False
    
    def apply(self, state: State, context: ActionContext,
              event_queue: MutableSequence[BaseEvent]) -> None:
        # 执行触发动作
        new_context = ActionContext(
            source=context.source,
            source_side=context.source_side,
            trigger_event=context.trigger_event,
            trigger_type="on_damage_taken"
        )
        self.trigger_action.execute(state, new_context, event_queue)
```

## 目标解析实现

```python
class TargetResolver:
    """目标解析器实现"""
    
    @staticmethod
    def resolve(target: TargetType,
                state: State,
                source_side: int,
                source_character: CharacterID) -> List[CharacterID]:
        """解析目标为角色 ID 列表"""
        game = state.game
        source_side_obj = game.sides[source_side]
        target_side = source_side if target.side == SideDescType.mine else (
            1 - source_side if target.side == SideDescType.enemy else None
        )
        
        result: List[CharacterID] = []
        
        if target.target == TargetDescType.active:
            if target_side is not None:
                side_obj = game.sides[target_side]
                active_char = side_obj.get_active_character()
                result.append(active_char.id)
        
        elif target.target == TargetDescType.active_next:
            if target_side is not None:
                side_obj = game.sides[target_side]
                characters = side_obj.characters
                active_idx = next(
                    (i for i, c in enumerate(characters) 
                     if c.id == side_obj.active_character_id),
                    -1
                )
                if active_idx >= 0 and active_idx + 1 < len(characters):
                    result.append(characters[active_idx + 1].id)
        
        elif target.target == TargetDescType.all_active:
            if target_side is not None:
                side_obj = game.sides[target_side]
                result.extend([c.id for c in side_obj.characters])
            elif target.side == SideDescType.both:
                for side_obj in game.sides:
                    result.extend([c.id for c in side_obj.characters])
        
        elif target.target == TargetDescType.self:
            result.append(source_character)
        
        elif target.target == TargetDescType.selected:
            if target.specific_id is not None:
                result.append(target.specific_id)
        
        # ... 其他目标类型的解析
        
        return result
```

## 使用示例

### 技能定义

```python
# 创建一个带多个动作的技能
skill = Skill_ElementalSkill(
    name="水元素战技",
    element=DamageElement.Hydro,
    cost=make_elemental_skill_cost(CostElement.Hydro, 3)
)

# 添加动作：对敌方站场角色造成 2 点水元素伤害
skill.actions.append(
    DamageAction(
        target=TargetType(TargetDescType.active, SideDescType.enemy),
        element=DamageElement.Hydro,
        value=2
    )
)

# 添加动作：对下一个角色造成 1 点水元素伤害（连锁）
skill.actions.append(
    DamageAction(
        target=TargetType(TargetDescType.active_next, SideDescType.enemy),
        element=DamageElement.Hydro,
        value=1,
        chain=True
    )
)

# 添加动作：附着水元素
skill.actions.append(
    ElementalApplicationAction(
        target=TargetType(TargetDescType.active, SideDescType.enemy),
        element=Element.Hydro
    )
)
```

## 扩展性

### 添加新的目标类型

1. 在 `TargetDescType` 枚举中添加新类型
2. 在 `TargetResolver.resolve()` 中实现解析逻辑
3. 更新文档

### 添加新的动作类型

1. 在 `ActionType` 枚举中添加新类型
2. 创建新的动作类继承 `BaseAction`
3. 实现 `execute()` 和 `can_execute()` 方法
4. 创建对应的事件类型（如果需要）
5. 更新配置解析器

## 注意事项

1. **目标解析顺序**：多个目标时，需要明确执行顺序
2. **连锁动作**：连锁动作需要正确处理边界情况（没有下一个目标）
3. **上下文传递**：确保上下文信息在动作链中正确传递
4. **性能考虑**：目标解析可能频繁执行，需要优化
5. **空目标处理**：当目标解析为空时，动作应该优雅地跳过

## 与现有系统集成

- **事件系统**：动作通过事件系统执行
- **Hook 系统**：动作执行可以被 Hook 拦截和修改
- **效果系统**：效果可以触发动作
- **状态系统**：动作可以查询和修改游戏状态

