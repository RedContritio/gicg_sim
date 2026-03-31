# GICG Sim 设计文档总览

## 文档索引

### 架构设计

| 文档 | 内容 | 状态 |
|------|------|------|
| [engine_architecture.md](./engine_architecture.md) | ECS + 事件驱动核心架构 | 完成 |
| [engine_test_cases.md](./engine_test_cases.md) | 角色测试案例（菲谢尔/阿蕾奇诺/甘雨等） | 完成 |

### RL 优化方案（三种方案对比）

| 文档 | 方案 | 核心思想 | 适用场景 |
|------|------|----------|----------|
| [engine_rl_optimized.md](./engine_rl_optimized.md) | 分层策略 | JSON(80%) + 简化Lua(15%) + 纯Go(5%) | 生产环境 |
| [engine_rl_features.md](./engine_rl_features.md) | 人工特征嵌入 | 预计算16维技能特征向量 | 快速实现 |
| [engine_code_as_observation.md](./engine_code_as_observation.md) | Code-as-Observation | 网络直接学习Lua代码 | 研究探索 |

## 关键决策点

### 1. 核心架构
- **ECS模式**: Entity-Component-System，数据与逻辑分离
- **事件驱动**: 被动技能通过事件订阅实现
- **预编译缓存**: 技能模板化，运行时O(1)查表

### 2. Lua边界
- **简化DSL**: 限制语法，12个核心API
- **单次调用**: Lua只读预计算上下文，返回纯数据
- **不回调Go**: 避免边界开销

### 3. RL观察值（待决策）
- 方案A: 人工特征（16维/技能，易实现）
- 方案B: 代码Token（128维/技能，客观完整）
- 方案C: 混合方案（先人工，后迁移到代码）

## 下一步设计任务

- [ ] C API设计（Python绑定）
- [ ] 状态序列化（MCTS支持）
- [ ] 动作空间精确定义
- [ ] 训练流程设计（PPO + MCTS）
- [ ] 性能基准测试方案

---

**当前待决策**: RL观察值方案选择（A/B/C）？
