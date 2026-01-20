# 项目结构设计文档

## 重构后的目录结构

```
gicg_sim/
├── core/                      # 核心游戏逻辑（无外部依赖，可独立运行）
│   ├── constants/             # 游戏常量定义
│   ├── entities/              # 游戏实体（角色、卡牌、技能等）
│   ├── game_state/            # 游戏状态管理
│   ├── mechanics/             # 游戏机制（伤害、反应、消耗等）
│   ├── events/                # 事件系统
│   ├── skills/                # 技能系统（纯 DSL）
│   │   ├── skill_loader.py    # 技能加载器
│   │   ├── skill_executor.py  # 技能执行器
│   │   ├── skill_metadata.py  # 技能元数据
│   │   ├── dsl/               # DSL 解析和执行
│   │   │   ├── parser.py      # DSL 解析器
│   │   │   ├── executor.py    # DSL 执行器
│   │   │   ├── expression.py # 表达式求值
│   │   │   ├── condition.py  # 条件判断
│   │   │   ├── effects.py     # 效果实现
│   │   │   └── triggers.py    # 触发器系统
│   │   └── validator.py       # 配置验证器
│   └── config/                # 配置管理
│       ├── skill_config.py    # 技能配置
│       └── loader.py           # 配置加载器
│
├── env/                       # RL 环境接口层
│   ├── base_env.py            # 基础环境类（类似 gym.Env）
│   ├── gicg_env.py            # GICG 环境实现
│   ├── action_space.py        # 动作空间定义
│   ├── observation_space.py   # 状态空间定义
│   ├── reward.py              # 奖励函数
│   ├── features/              # 特征提取
│   │   ├── skill_feature_extractor.py  # 技能特征提取
│   │   └── skill_encoder.py           # 技能编码器
│   └── wrappers/              # 环境包装器
│
├── gui/                       # GUI 接口层
│   ├── game_controller.py     # 游戏控制器
│   ├── event_listener.py      # 事件监听
│   └── game_replay.py         # 游戏回放
│
├── ai/                        # AI 智能体
│   ├── base_agent.py          # 智能体基类
│   └── random_agent.py        # 随机策略
│
├── utils/                     # 工具函数
│   ├── serialization.py       # 序列化
│   └── visualization.py       # 可视化
│
├── characters/                # 角色实现
│   ├── __init__.py
│   ├── base.py                # 角色基类扩展
│   └── khaenriahn.py          # 示例角色
│
└── configs/                   # 配置文件目录
    ├── skills/                # 技能配置文件
    │   ├── khaenriahn/
    │   │   ├── normal_attack.yaml
    │   │   ├── elemental_skill.yaml
    │   │   └── elemental_burst.yaml
    │   └── ...
    └── cards/                 # 卡牌配置文件
        └── ... 
```

## 核心模块设计

### 1. core/ - 核心游戏逻辑

#### core/constants/
- **element.py**：元素枚举（Element, DiceElement, CostElement, DamageElement）
- **skill.py**：技能类型（NormalAttack, ElementalSkill, ElementalBurst）
- **target.py**：目标类型（ActiveCharacter, AllCharacters, Summon, etc.）
- **game_config.py**：游戏配置常量
  ```python
  MAX_HAND_SIZE = 16
  MAX_SUPPORTERS = 4
  MAX_SUMMONS = 4
  MAX_DICES = 12
  MAX_CHARACTERS = 3  # 玩家
  MAX_CHARACTERS_NPC = 6  # NPC
  ```

#### core/entities/
- **character.py**：角色类
  ```python
  class Character:
      id: CharacterID
      name: str
      max_hp: int
      current_hp: int
      max_energy: int
      current_energy: int
      element: Element
      skills: List[Skill]
      status_effects: List[StatusEffect]
  ```
- **card.py**：卡牌类
- **skill.py**：技能类（BaseSkill, NormalAttack, ElementalSkill, ElementalBurst）
- **summon.py**：召唤物类
- **supporter.py**：支援牌类

#### core/game_state/
- **player_side.py**：玩家方状态
  ```python
  class PlayerSide:
      characters: List[Character]
      backup_characters: List[List[Character]]
      cards_hand: List[Card]
      cards_deck: List[Card]
      cards_discard: List[Card]
      supporters: List[Supporter]
      summons: List[Summon]
      dices: DiceState
      active_character_id: CharacterID | None
  ```
- **game_state.py**：完整游戏状态
  ```python
  class GameState:
      player_side: PlayerSide
      opponent_side: PlayerSide
      current_turn: int
      current_player: int  # 0: player, 1: opponent
      phase: GamePhase  # Prepare, Action, End
      event_queue: EventQueue
  ```
- **state_snapshot.py**：状态快照（用于回放、撤销）

#### core/mechanics/
- **damage.py**：伤害计算和伤害队列
- **reaction.py**：元素反应（增幅、剧变）
- **cost.py**：消耗验证和计算
- **dice.py**：骰子管理和操作

#### core/events/
- **base.py**：BaseEvent 基类
- **damage_event.py**：DamageEvent
- **cost_event.py**：CostEvent
- **skill_event.py**：SkillEvent
- **event_queue.py**：事件队列和处理器
  ```python
  class EventQueue:
      def push(self, event: BaseEvent)
      def process(self) -> List[EventResult]
      def clear(self)
  ```

### 2. env/ - RL 环境接口

#### env/base_env.py
```python
class BaseEnv:
    """类似 gym.Env 的接口"""
    def reset(self, seed: int | None = None) -> Observation
    def step(self, action: Action) -> Tuple[Observation, Reward, bool, Info]
    def render(self, mode: str = 'human')
    
    @property
    def observation_space(self) -> Space
    @property
    def action_space(self) -> Space
```

#### env/gicg_env.py
```python
class GicgEnv(BaseEnv):
    """GICG 环境实现"""
    def __init__(self, config: EnvConfig)
    # 实现 BaseEnv 的所有方法
    # 管理游戏状态
    # 处理动作执行
    # 计算奖励
```

#### env/action_space.py
```python
class ActionSpace:
    """动作空间定义"""
    # 动作类型：
    # - USE_SKILL: (character_id, skill_type)
    # - SWITCH_CHARACTER: (character_id)
    # - USE_CARD: (card_index)
    # - TUNE_DICE: (dice_index, target_element)
    # - END_TURN: ()
    
    def encode(self, action: Action) -> np.ndarray
    def decode(self, encoded: np.ndarray) -> Action
    def get_valid_actions(self, state: GameState) -> List[Action]
```

#### env/observation_space.py
```python
class ObservationSpace:
    """状态空间定义"""
    def encode(self, state: GameState) -> np.ndarray
    # 编码玩家方完整状态
    # 编码对手方部分可观测状态
    # 编码游戏全局状态
    # 编码技能特征（从技能元数据提取）
```

#### env/features/
- **skill_feature_extractor.py**：技能特征提取器
  - 从技能元数据提取特征
  - 从 DSL 配置提取特征（元数据、效果摘要、结构特征）
  - 组合技能特征向量
- **skill_encoder.py**：技能编码器
  - 将技能编码为固定维度的特征向量
  - 支持批量编码

#### env/reward.py
```python
class RewardFunction:
    """奖励函数"""
    def calculate(self, 
                  prev_state: GameState,
                  action: Action,
                  next_state: GameState,
                  done: bool) -> float
```

### 3. gui/ - GUI 接口层

#### gui/game_controller.py
```python
class GameController:
    """GUI 调用的游戏控制器"""
    def start_new_game(self, 
                       player_deck: List[Card],
                       opponent_deck: List[Card]) -> GameID
    
    def get_game_state(self, game_id: GameID) -> GameState
    
    def execute_action(self, 
                       game_id: GameID, 
                       action: Action) -> ActionResult
    
    def get_valid_actions(self, game_id: GameID) -> List[Action]
    
    def subscribe_events(self, 
                         game_id: GameID,
                         callback: Callable[[Event], None])
    
    def save_game(self, game_id: GameID) -> bytes
    
    def load_game(self, data: bytes) -> GameID
```

#### gui/event_listener.py
```python
class EventListener:
    """事件监听器，用于 UI 更新"""
    def on_damage(self, event: DamageEvent)
    def on_skill_used(self, event: SkillEvent)
    def on_character_switched(self, event: SwitchEvent)
    # ... 其他事件
```

### 4. ai/ - AI 智能体

#### ai/base_agent.py
```python
class BaseAgent:
    """智能体基类"""
    def select_action(self, 
                     observation: Observation,
                     valid_actions: List[Action]) -> Action
```

#### ai/random_agent.py
```python
class RandomAgent(BaseAgent):
    """随机策略智能体（用于测试）"""
    def select_action(self, observation, valid_actions) -> Action:
        return random.choice(valid_actions)
```

## 数据流设计

### RL 训练流程
```
1. env.reset() -> Observation
2. agent.select_action(observation) -> Action
3. env.step(action) -> (Observation, Reward, Done, Info)
4. 如果 Done=False，回到步骤 2
5. 如果 Done=True，回到步骤 1
```

### GUI 游戏流程
```
1. GameController.start_new_game() -> GameID
2. GUI 订阅事件
3. GUI 显示当前状态
4. 用户选择动作
5. GameController.execute_action() -> ActionResult
6. 事件触发，GUI 更新
7. 如果游戏未结束，回到步骤 3
```

## 状态表示

### Observation（状态向量）
```python
observation = {
    # 玩家方状态（完整）
    'player_characters': np.array([...]),  # 角色信息
    'player_hand': np.array([...]),        # 手牌
    'player_dices': np.array([...]),       # 骰子
    'player_supporters': np.array([...]),  # 支援区
    'player_summons': np.array([...]),     # 召唤物
    
    # 对手方状态（部分可观测）
    'opponent_characters_hp': np.array([...]),  # 仅生命值
    'opponent_characters_element': np.array([...]),  # 仅元素
    'opponent_hand_count': int,  # 仅手牌数量
    'opponent_dice_count': int,  # 仅骰子数量
    
    # 全局状态
    'current_turn': int,
    'current_player': int,
    'game_phase': int,
}
```

### Action（动作）
```python
action = {
    'type': ActionType,  # USE_SKILL, SWITCH_CHARACTER, etc.
    'params': dict,      # 动作参数
}
```

## 关键设计决策

1. **核心逻辑与接口分离**：`core/` 模块不依赖 RL 或 GUI，可独立使用
2. **状态不可变性**：游戏状态使用不可变数据结构，便于快照和回放
3. **事件驱动**：所有游戏变化通过事件系统，便于 GUI 更新和调试
4. **动作验证**：在动作执行前验证合法性，返回明确的错误信息
5. **部分可观测**：对手方状态部分隐藏，增加游戏策略性
