# 架构设计文档

## 整体架构

```
┌─────────────────────────────────────────────────────────┐
│                     应用层                                │
├──────────────────┬──────────────────┬───────────────────┤
│   RL 训练环境     │   GUI 游戏界面    │   其他应用         │
└────────┬─────────┴────────┬─────────┴────────┬──────────┘
         │                  │                  │
         ▼                  ▼                  ▼
┌─────────────────────────────────────────────────────────┐
│                     接口层                                │
├──────────────────┬──────────────────┬───────────────────┤
│   env/           │   gui/           │   ai/             │
│   (RL 环境)      │   (GUI 控制器)    │   (AI 智能体)      │
└────────┬─────────┴────────┬─────────┴────────┬──────────┘
         │                  │                  │
         └──────────────────┴──────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────┐
│                     核心层                                │
│                      core/                               │
│  ┌──────────┬──────────┬──────────┬──────────┐         │
│  │ entities │ game_state│mechanics│ events   │         │
│  └──────────┴──────────┴──────────┴──────────┘         │
└─────────────────────────────────────────────────────────┘
```

## 核心层设计（core/）

### 设计原则
1. **无外部依赖**：核心层不依赖 env、gui、ai 等上层模块
2. **纯函数式**：尽可能使用不可变数据结构和纯函数
3. **事件驱动**：所有状态变更通过事件系统
4. **可测试性**：每个模块都可以独立测试

### 模块职责

#### core/entities/
定义游戏中的实体对象：
- **Character**：角色实体
- **Card**：卡牌实体
- **Skill**：技能实体
- **Summon**：召唤物实体
- **Supporter**：支援牌实体

这些实体是**数据类**，不包含游戏逻辑。

#### core/game_state/
管理游戏状态：
- **PlayerSide**：玩家方的完整状态
- **GameState**：完整的游戏状态（包含双方）
- **StateSnapshot**：状态快照（用于回放、撤销）

状态应该是**不可变的**，每次修改返回新状态。

#### core/mechanics/
实现游戏机制：
- **DamageCalculator**：伤害计算
- **ReactionSystem**：元素反应系统
- **CostValidator**：消耗验证
- **DiceManager**：骰子管理

这些是**纯函数**或**无状态类**。

#### core/events/
事件系统：
- **BaseEvent**：事件基类
- **EventQueue**：事件队列
- **EventProcessor**：事件处理器
- **EventHook**：事件钩子（用于技能效果等）

## 接口层设计

### env/ - RL 环境接口

#### 接口设计
```python
class GicgEnv:
    """GICG 强化学习环境"""
    
    def __init__(self, config: EnvConfig):
        self._game_state: GameState = None
        self._config = config
    
    def reset(self, seed: int | None = None) -> Observation:
        """重置环境，返回初始状态"""
        # 1. 初始化游戏状态
        # 2. 编码为 Observation
        # 3. 返回
    
    def step(self, action: Action) -> Tuple[Observation, float, bool, dict]:
        """执行动作，返回 (状态, 奖励, 是否结束, 信息)"""
        # 1. 验证动作合法性
        # 2. 执行动作（通过 core 层）
        # 3. 处理事件队列
        # 4. 计算奖励
        # 5. 检查游戏是否结束
        # 6. 编码新状态
        # 7. 返回结果
    
    def render(self, mode: str = 'human'):
        """渲染当前状态（可选）"""
        pass
    
    @property
    def observation_space(self) -> Space:
        """返回状态空间定义"""
        return self._observation_space
    
    @property
    def action_space(self) -> Space:
        """返回动作空间定义"""
        return self._action_space
```

#### 状态编码
```python
def encode_state(game_state: GameState, player_id: int) -> np.ndarray:
    """将游戏状态编码为数值向量"""
    # 玩家方完整状态
    player_side = game_state.get_side(player_id)
    player_vec = encode_player_side(player_side)
    
    # 对手方部分可观测状态
    opponent_id = 1 - player_id
    opponent_side = game_state.get_side(opponent_id)
    opponent_vec = encode_opponent_side_partial(opponent_side)
    
    # 全局状态
    global_vec = encode_global_state(game_state)
    
    return np.concatenate([player_vec, opponent_vec, global_vec])
```

#### 动作解码
```python
def decode_action(encoded: np.ndarray) -> Action:
    """将编码的动作解码为 Action 对象"""
    action_type = ActionType(encoded[0])
    params = decode_params(encoded[1:], action_type)
    return Action(type=action_type, params=params)
```

#### 动作验证
```python
def get_valid_actions(game_state: GameState, player_id: int) -> List[Action]:
    """获取当前状态下所有有效动作"""
    valid_actions = []
    player_side = game_state.get_side(player_id)
    
    # 检查技能动作
    for character in player_side.characters:
        for skill in character.skills:
            if can_use_skill(player_side, skill):
                valid_actions.append(Action.use_skill(character.id, skill.type))
    
    # 检查切换角色动作
    for character in player_side.characters:
        if character.id != player_side.active_character_id:
            valid_actions.append(Action.switch_character(character.id))
    
    # 检查使用卡牌动作
    for i, card in enumerate(player_side.cards_hand):
        if can_use_card(player_side, card):
            valid_actions.append(Action.use_card(i))
    
    # 检查调和骰子动作
    # ...
    
    # 结束回合总是有效的
    valid_actions.append(Action.end_turn())
    
    return valid_actions
```

### gui/ - GUI 接口

#### GameController 设计
```python
class GameController:
    """游戏控制器，GUI 调用的主要接口"""
    
    def __init__(self):
        self._games: Dict[GameID, GameState] = {}
        self._event_listeners: Dict[GameID, List[Callable]] = {}
    
    def start_new_game(self, 
                       player_deck: List[Card],
                       opponent_deck: List[Card],
                       opponent_agent: BaseAgent | None = None) -> GameID:
        """开始新游戏"""
        game_id = generate_game_id()
        game_state = initialize_game(player_deck, opponent_deck)
        self._games[game_id] = game_state
        
        # 如果对手是 AI，启动 AI 线程
        if opponent_agent:
            self._start_ai_thread(game_id, opponent_agent)
        
        return game_id
    
    def get_game_state(self, game_id: GameID) -> GameState:
        """获取游戏状态（用于 UI 渲染）"""
        return self._games[game_id]
    
    def execute_action(self, 
                       game_id: GameID, 
                       action: Action) -> ActionResult:
        """执行玩家动作"""
        game_state = self._games[game_id]
        
        # 验证动作
        if not is_action_valid(game_state, action):
            return ActionResult.error("Invalid action")
        
        # 执行动作
        new_state, events = apply_action(game_state, action)
        self._games[game_id] = new_state
        
        # 触发事件监听器
        self._notify_listeners(game_id, events)
        
        # 如果是 AI 回合，触发 AI 决策
        if new_state.current_player == 1:  # 对手
            self._trigger_ai_action(game_id)
        
        return ActionResult.success(new_state, events)
    
    def get_valid_actions(self, game_id: GameID) -> List[Action]:
        """获取当前有效动作列表"""
        game_state = self._games[game_id]
        return get_valid_actions(game_state, game_state.current_player)
    
    def subscribe_events(self, 
                         game_id: GameID,
                         callback: Callable[[Event], None]):
        """订阅游戏事件（用于 UI 更新）"""
        if game_id not in self._event_listeners:
            self._event_listeners[game_id] = []
        self._event_listeners[game_id].append(callback)
```

#### 事件监听机制
```python
class EventListener:
    """事件监听器，处理各种游戏事件"""
    
    def on_damage(self, event: DamageEvent):
        """伤害事件：更新角色生命值显示，播放伤害动画"""
        pass
    
    def on_skill_used(self, event: SkillEvent):
        """技能使用事件：播放技能动画"""
        pass
    
    def on_character_switched(self, event: SwitchEvent):
        """角色切换事件：更新活跃角色显示"""
        pass
    
    def on_card_played(self, event: CardEvent):
        """卡牌使用事件：从手牌移除，播放卡牌效果"""
        pass
```

## 数据流

### RL 训练数据流
```
Agent
  │
  │ select_action(observation)
  ▼
Action (编码)
  │
  │ env.step(action)
  ▼
GicgEnv
  │
  │ 1. 验证动作
  │ 2. 执行动作（调用 core）
  │ 3. 处理事件
  │ 4. 计算奖励
  │ 5. 编码新状态
  ▼
(Observation, Reward, Done, Info)
  │
  ▼
Agent (更新策略)
```

### GUI 游戏数据流
```
GUI
  │
  │ user_input
  ▼
GameController
  │
  │ execute_action()
  ▼
Core (GameState + Events)
  │
  │ 1. 应用动作
  │ 2. 生成事件
  │ 3. 更新状态
  ▼
GameState (新状态)
  │
  │ notify_listeners()
  ▼
EventListeners
  │
  │ on_event()
  ▼
GUI (更新 UI)
```

## 关键接口定义

### Action 接口
```python
@dataclass
class Action:
    """游戏动作"""
    type: ActionType
    params: Dict[str, Any]
    
    @classmethod
    def use_skill(cls, character_id: CharacterID, skill_type: SkillType):
        return cls(ActionType.USE_SKILL, {
            'character_id': character_id,
            'skill_type': skill_type
        })
    
    @classmethod
    def switch_character(cls, character_id: CharacterID):
        return cls(ActionType.SWITCH_CHARACTER, {
            'character_id': character_id
        })
    
    @classmethod
    def use_card(cls, card_index: int):
        return cls(ActionType.USE_CARD, {
            'card_index': card_index
        })
    
    @classmethod
    def end_turn(cls):
        return cls(ActionType.END_TURN, {})
```

### Event 接口
```python
class BaseEvent(ABC):
    """事件基类"""
    timestamp: float
    
@dataclass
class DamageEvent(BaseEvent):
    source: CharacterID
    target: TargetType
    element: DamageElement
    value: int
    final_value: int  # 经过反应和修改后的最终值

@dataclass
class SkillEvent(BaseEvent):
    character_id: CharacterID
    skill_type: SkillType
    skill_name: str
```

### GameState 接口
```python
@dataclass(frozen=True)  # 不可变
class GameState:
    """游戏状态（不可变）"""
    player_side: PlayerSide
    opponent_side: PlayerSide
    current_turn: int
    current_player: int
    phase: GamePhase
    
    def apply_action(self, action: Action) -> Tuple['GameState', List[BaseEvent]]:
        """应用动作，返回新状态和事件列表"""
        # 实现状态转换逻辑
        pass
```

## 性能考虑

1. **状态编码优化**：使用 numpy 数组，避免 Python 对象开销
2. **事件批处理**：批量处理事件，减少函数调用开销
3. **状态快照**：使用深拷贝优化，或使用不可变数据结构
4. **动作验证缓存**：缓存有效动作列表，避免重复计算
5. **并行化**：支持多环境并行训练（使用 gymnasium 的 AsyncVectorEnv）

## 扩展性设计

1. **新角色**：在 `characters/` 目录添加新角色类
2. **新卡牌**：在 `core/entities/card.py` 扩展卡牌类型
3. **新机制**：在 `core/mechanics/` 添加新机制模块
4. **新事件**：在 `core/events/` 添加新事件类型
5. **新 AI**：在 `ai/` 添加新的智能体实现
