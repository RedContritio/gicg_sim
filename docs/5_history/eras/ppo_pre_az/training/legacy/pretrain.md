# 历史训练方案 — Instruction Encoder 预训练

> [legacy/README.md](README.md) 第 2 节。

## 2. Instruction Encoder 预训练

在 RL 课程之前，先单独训练 Instruction Encoder 学会"读懂 DSL"。

### 核心思路：执行跟踪预测

用引擎跑大量随机对局，采集每步的 hook 触发记录。训练网络预测：在当前状态下，如果这个 hook 触发，哪些 counter 会变化，变化多少？

Shuffle 是关键——没有 shuffle 网络可以死记 "位置 5 = HP"；有了 shuffle 必须通过 AST 理解语义。

### 数据生成

```
引擎配置：随机策略双方对局，全量记录
每步记录：
  - 当前 counter 快照（shuffle 后）
  - 触发的 hook 的 AST（shuffle 后）
  - 执行后 counter 变化量（delta）

生成量：10 万局随机对局 ≈ 300-800 万样本
引擎速度：Go + LuaJIT，单线程约 1000 局/秒，64 线程 ≈ 数分钟完成
```

### 三阶段预训练

**Stage P1：单步预测（基础 DSL 理解）**

```
输入：(Counter 区 [Nx3], Hook AST 区 [MxD], 执行的动作 ID)
标签：每个 counter 的 delta (value_after - value_before)
损失：Huber loss
数据：仅 L1-L2 卡牌，1v1 同角色
```

网络学会读简单 DSL：`deal_damage(target, FIRE, 3)` → "某个 counter 会减少 3"。

**Stage P2：复杂 DSL 理解**

```
输入：同 P1
标签：同 P1
数据：逐步扩大到 L1-L4 卡牌，1v1 异角色（引入元素反应）
```

网络学会读条件分支和连锁效果。

**Stage P3：多步预测 + 价值热启动**

```
多步预测：
  输入：(Counter 区, Hook 区, 连续 3 步动作序列)
  标签：3 步后 counter 状态
  训练连锁推理：泼墨追加伤害 → 元素反应 → 连锁 hook

价值热启动：
  输入：(Counter 区, Hook 区)
  标签：该局最终胜负（来自随机 rollout）
  给 Value Head 一个粗糙但非零的初始化
  数据：L1-L6 全量，1v1 + 2v2
```

### 预训练产出

```
冻结权重：Instruction Encoder (AST Token Encoder + Self-Attention)
可选保留：预测 Head（作为 RL 阶段的辅助损失）
迁移到 RL：State Encoder + Grounding Attention 从 P3 热启动
```
