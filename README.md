# GICG Sim - 原神七圣召唤模拟器

一个用于模拟和测试《原神》七圣召唤卡牌游戏机制的 Python 框架。

## 项目简介

GICG Sim 是一个事件驱动的游戏模拟器，旨在提供完整的七圣召唤游戏逻辑实现。该项目可用于：
- 游戏机制测试和验证
- AI 算法开发和训练
- 游戏数据分析
- 策略研究和优化

## 功能特性

### 已实现功能

- ✅ **基础游戏框架**
  - 双人对战系统
  - 游戏状态管理
  - 事件队列系统

- ✅ **角色系统**
  - 角色属性（生命值、能量、元素）
  - 技能系统（普通攻击、元素战技、元素爆发）
  - 从 YAML 配置文件加载角色

- ✅ **骰子系统**
  - 元素骰子管理（火、水、风、雷、草、冰、岩、万能）
  - 费用检查和消耗
  - 元素调和功能

- ✅ **基础事件系统**
  - 技能事件
  - 伤害事件
  - 费用事件

### 开发中功能

- 🚧 **伤害计算系统**
  - 元素反应（增幅反应、剧变反应）
  - 伤害队列和修改机制

- 🚧 **完整战斗流程**
  - 回合管理
  - 行动阶段处理

### 计划功能

- ⏳ **卡牌系统**
  - 手牌管理
  - 支援牌系统
  - 装备牌系统

- ⏳ **召唤物系统**
  - 召唤物创建和管理
  - 召唤物效果触发

- ⏳ **状态系统**
  - 角色状态效果
  - 状态持续时间和移除

- ⏳ **Hook 系统**
  - 事件钩子机制
  - 效果触发和修改

## 项目结构

```
gicg_sim/
├── gicg_sim/              # 主代码目录
│   ├── constants/         # 常量定义（元素、技能类型、目标等）
│   ├── data/              # 数据文件（角色配置 YAML）
│   └── game/              # 游戏核心逻辑
│       ├── character/     # 角色系统
│       ├── event/         # 事件系统
│       ├── state/         # 状态管理
│       └── ...            # 其他游戏组件
├── docs/                  # 文档目录
│   ├── architect.md       # 架构设计文档
│   ├── roadmap.md         # 开发路线图
│   └── rules.md           # 游戏规则和开发规则
├── tests/                 # 测试文件
└── pyproject.toml         # 项目配置
```

## 快速开始

### 安装依赖

项目使用 Poetry 管理依赖：

```bash
poetry install
```

### 基本使用

```python
import gicg_sim
from gicg_sim.game.character.loader import load_character_by_name
from gicg_sim.constants.id import CharacterID

# 创建游戏实例
game = gicg_sim.Game()

# 加载角色
character = load_character_by_name("test_pyro", CharacterID(0))

# 使用技能
game.player_use_skill("普通攻击")
```

### 运行测试

```bash
poetry run pytest
```

## 配置角色

角色通过 YAML 文件配置，位于 `gicg_sim/data/characters/` 目录：

```yaml
name: TestPyro
element: Pyro
max_hp: 10
max_energy: 2

skills:
  - name: 普通攻击
    type: normal_attack
    damage_element: Physical
    damage_count: 2
    cost:
      element: Pyro
      element_count: 1
      any_count: 2
```

## 开发规范

请参考 [docs/rules.md](docs/rules.md) 了解详细的开发规则和游戏规则。

## 开发路线图

请参考 [docs/roadmap.md](docs/roadmap.md) 了解详细的开发计划和进度。

## 贡献

欢迎提交 Issue 和 Pull Request！

## 许可证

[待定]

## 作者

RedContritio <RedContritio@qq.com>

