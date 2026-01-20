# GICG Sim 项目总结

## 项目概述

**GICG Sim** 是一个原神卡牌游戏（Genshin Impact Card Game）的模拟器项目，主要设计目标为：

1. **强化学习（RL）训练环境**：提供标准的 RL 环境接口，支持智能体训练
2. **GUI 游戏接口**：为图形界面提供游戏逻辑调用接口
3. **单人游戏场景**：支持玩家 vs AI 或玩家 vs 环境的游戏模式

## 设计目标

### RL 环境需求
- 标准化的环境接口（类似 Gym/Gymnasium）
- 清晰的状态表示（Observation Space）
- 明确的动作空间（Action Space）
- 奖励函数设计
- 回合制游戏流程管理
- 状态序列化和反序列化（用于训练数据）

### GUI 接口需求
- 游戏状态查询接口
- 动作执行接口
- 事件通知机制（用于 UI 更新）
- 游戏回放支持
- 状态快照和恢复

### 单人游戏需求
- 玩家控制一方，AI/环境控制另一方
- 清晰的回合切换机制
- 游戏结束判定
- 胜负统计

## 重构后的项目结构

```
gicg_sim/
├── core/                      # 核心游戏逻辑（无外部依赖）
│   ├── __init__.py
│   ├── constants/             # 游戏常量
│   │   ├── __init__.py
│   │   ├── element.py         # 元素类型枚举
│   │   ├── skill.py           # 技能类型
│   │   ├── target.py          # 目标类型
│   │   └── game_config.py     # 游戏配置（上限、规则等）
│   │
│   ├── entities/              # 游戏实体
│   │   ├── __init__.py
│   │   ├── character.py       # 角色类
│   │   ├── card.py            # 卡牌类
│   │   ├── skill.py           # 技能类
│   │   ├── summon.py          # 召唤物
│   │   └── supporter.py       # 支援牌
│   │
│   ├── game_state/            # 游戏状态管理
│   │   ├── __init__.py
│   │   ├── player_side.py     # 玩家方状态（手牌、角色、骰子等）
│   │   ├── game_state.py      # 完整游戏状态
│   │   └── state_snapshot.py  # 状态快照（用于回放、撤销）
│   │
│   ├── mechanics/             # 游戏机制
│   │   ├── __init__.py
│   │   ├── damage.py          # 伤害计算
│   │   ├── reaction.py        # 元素反应
│   │   ├── cost.py            # 消耗计算
│   │   └── dice.py            # 骰子管理
│   │
│   └── events/                # 事件系统
│       ├── __init__.py
│       ├── base.py            # 事件基类
│       ├── damage_event.py    # 伤害事件
│       ├── cost_event.py      # 消耗事件
│       ├── skill_event.py     # 技能事件
│       └── event_queue.py     # 事件队列和处理器
│
├── env/                       # RL 环境接口
│   ├── __init__.py
│   ├── base_env.py            # 基础环境类（类似 gym.Env）
│   ├── gicg_env.py            # GICG 环境实现
│   ├── action_space.py        # 动作空间定义
│   ├── observation_space.py   # 状态空间定义
│   ├── reward.py              # 奖励函数
│   └── wrappers/              # 环境包装器
│       ├── __init__.py
│       ├── action_mask.py     # 动作掩码（过滤无效动作）
│       └── state_normalize.py # 状态归一化
│
├── gui/                       # GUI 接口层
│   ├── __init__.py
│   ├── game_controller.py     # 游戏控制器（GUI 调用接口）
│   ├── event_listener.py      # 事件监听器（用于 UI 更新）
│   └── game_replay.py         # 游戏回放功能
│
├── ai/                        # AI 相关
│   ├── __init__.py
│   ├── base_agent.py          # AI 智能体基类
│   ├── random_agent.py        # 随机策略智能体
│   └── mcts_agent.py          # MCTS 智能体（可选）
│
├── utils/                     # 工具函数
│   ├── __init__.py
│   ├── serialization.py       # 状态序列化（用于保存/加载）
│   └── visualization.py       # 状态可视化（调试用）
│
└── characters/                # 角色实现
    ├── __init__.py
    ├── base.py                # 角色基类扩展
    └── khaenriahn.py          # 示例角色
```

## 核心设计

### 1. RL 环境接口（env/）

#### BaseEnv（类似 gym.Env）
```python
class BaseEnv:
    def reset(self, seed=None) -> Observation
    def step(self, action: Action) -> Tuple[Observation, Reward, bool, dict]
    def render(self, mode='human')
    @property
    def observation_space(self) -> Space
    @property
    def action_space(self) -> Space
```

#### 状态空间（Observation Space）
- **玩家方状态**：
  - 角色信息（生命值、能量、元素、状态效果）
  - 手牌（卡牌 ID 列表）
  - 骰子（各元素数量）
  - 支援区、召唤物区
- **对手方状态**（部分可观测）：
  - 角色生命值（可见）
  - 角色元素（可见）
  - 手牌数量（可见）
  - 骰子数量（可见）
- **游戏全局状态**：
  - 当前回合
  - 当前行动方
  - 游戏阶段（准备、行动、结束等）

#### 动作空间（Action Space）
- **技能动作**：使用角色技能（角色ID + 技能类型）
- **切换角色**：切换到指定角色
- **使用卡牌**：使用手牌中的卡牌（卡牌索引）
- **调和骰子**：调和指定骰子
- **结束回合**：结束当前回合
- **无效动作**：当动作不可执行时返回错误

#### 奖励函数设计
- **即时奖励**：
  - 造成伤害：+0.1 × 伤害值
  - 受到伤害：-0.1 × 伤害值
  - 击败角色：+10.0
  - 角色被击败：-10.0
- **回合奖励**：
  - 回合结束时根据双方状态差计算
- **终局奖励**：
  - 胜利：+100.0
  - 失败：-100.0

### 2. GUI 接口层（gui/）

#### GameController
```python
class GameController:
    def __init__(self)
    def start_new_game(self, player_deck, opponent_deck) -> GameID
    def get_game_state(self, game_id: GameID) -> GameState
    def execute_action(self, game_id: GameID, action: Action) -> ActionResult
    def get_valid_actions(self, game_id: GameID) -> List[Action]
    def subscribe_events(self, game_id: GameID, callback: Callable)
    def save_game(self, game_id: GameID) -> bytes
    def load_game(self, data: bytes) -> GameID
```

#### 事件监听机制
- 游戏状态变化时触发事件
- GUI 可以订阅事件并更新 UI
- 支持事件回放（用于动画效果）

### 3. 核心游戏逻辑（core/）

#### 游戏状态管理
- **不可变状态**：使用不可变数据结构，便于状态快照和回放
- **状态验证**：每次状态变更前验证合法性
- **状态快照**：支持保存和恢复游戏状态

#### 事件驱动架构
- 所有游戏操作通过事件系统处理
- 事件队列按顺序执行
- 支持事件 hook（用于技能效果、卡牌效果等）
- 事件可以触发新事件（连锁反应）

#### 伤害和反应系统
- 伤害队列：管理未结算的伤害
- 元素反应：增幅反应、剧变反应
- 伤害修改：支持伤害加成、减免等效果

### 4. AI 智能体（ai/）

#### BaseAgent
```python
class BaseAgent:
    def select_action(self, observation: Observation, valid_actions: List[Action]) -> Action
```

#### 实现类型
- **RandomAgent**：随机选择有效动作（用于测试）
- **MCTSAgent**：蒙特卡洛树搜索（可选实现）
- **RLAgent**：由训练好的模型加载（外部提供）

## 技术栈

- **Python 3.12+**
- **gymnasium**（可选）：标准 RL 环境接口
- **numpy**：数值计算和状态表示
- **pyyaml**：YAML 配置文件解析（技能配置）
- **pyyaml**：配置文件解析

## 开发阶段

### 阶段 1：核心游戏逻辑
- [ ] 重构核心游戏状态管理
- [ ] 实现事件系统
- [ ] 实现伤害和反应系统
- [ ] 实现基础角色和技能

### 阶段 2：RL 环境接口
- [ ] 实现 BaseEnv 接口
- [ ] 定义状态空间和动作空间
- [ ] 实现奖励函数
- [ ] 实现动作验证和掩码

### 阶段 3：GUI 接口
- [ ] 实现 GameController
- [ ] 实现事件监听机制
- [ ] 实现游戏回放功能

### 阶段 4：AI 和测试
- [ ] 实现基础 AI 智能体
- [ ] 编写单元测试
- [ ] 编写集成测试
- [ ] 性能优化

## 设计原则

1. **关注点分离**：核心逻辑、RL 接口、GUI 接口分离
2. **可测试性**：每个模块都可以独立测试
3. **可扩展性**：易于添加新角色、新卡牌、新机制
4. **性能优先**：RL 训练需要大量模拟，性能至关重要
5. **状态一致性**：确保游戏状态始终合法和一致
