# 网络架构 (DEPRECATED)

> **⚠️ Deprecated as of 2026-04-14.** This directory describes the
> **PPO-era** network architecture, which is being replaced by the
> AlphaZero + IS-MCTS framework documented in
> [`docs/current/az/network_design.md`](../../../current/az/network_design.md).
>
> The AZ network reuses ~70% of the trunk (counter/hook/card encoders,
> cross-attention, pooling) but replaces the policy sampling path and
> value head training objective. See `docs/current/az/network_design.md` for
> the new architecture and `docs/current/az/decisions.md` D3, D8 for rationale.
>
> Everything below is kept for historical reference only.

---

> **⚠️ Legacy design doc.** §1-4 below describe the pre-refactor plan
> (Instruction Encoder / Grounding Attention / two-step Action+Target
> heads / AST token layout). The shipped architecture is in
> **`docs/network/implementation.md`** — read that first. The shuffle
> discipline (§1) is still accurate, but the policy head is now a
> pointer network (not two-step Action+Target), the hook encoder sees
> synthetic canonical tokens for skill/card action refs, and there's a
> CardEncoder for the hand block. This file is kept as historical
> context for the original design reasoning.

## 1. Shuffle 机制

对局初始化后，所有 counter 和 hook 展开为 flat 数组后：

1. 生成 counter 数组的随机排列 P，重映射所有 hook 中的 counter 引用
2. 生成 hook 数组的随机排列 Q
3. Agent 观测排列后的数组

强迫网络通过 attention 学习语义关系，而非记忆位置。

## 2. 观测空间

三个分区：

```
Counter 区（固定长度 N，已 shuffle）：
  每个 counter：[value, min, max]
  维度：N x 3

Hook 区（固定长度 M，已 shuffle）：
  每个 hook：序列化 AST 特征
  Lua hook 函数在加载时解析为 AST
  AST 节点类型（约 10 种）：if, compare, read, write, call, binop, const, return, local, for
  每个 AST 序列化为定长特征向量
  维度：M x D_hook

Action 区（动态长度，每步变化）：
  当前合法动作列表，每个动作指向一个 hook 索引
  两步决策：第一步选动作，第二步选目标
```

## 3. AST 序列化

Hook 函数使用 Lua 受限子集（约 10 种 AST 节点类型）。每个 hook 的 AST 线性化为 token 序列：

- 每个 AST 节点 → token：[node_type(one-hot), operator, counter_ref_index, const_value]
- Counter 引用为（shuffle 后的）counter 数组索引
- 序列填充/截断至固定长度

## 4. 网络架构

采用独立的 Instruction Encoder 将 DSL 理解与游戏决策解耦：

```
                    +---------------------------------+
                    |     Instruction Encoder          |
Hook AST 区 ------>|  (独立模块，预训练后可冻结)        |---> effect_embeddings (M x d)
                    |  AST Token Encoder + Self-Attn   |
                    +---------------------------------+
                                                              |
                                                              v
                                                     +------------------+
Counter 值区 --> [State Encoder MLP] --> state_emb -->|   Grounding      |--> grounded_repr
                                                     |   Cross-Attention |
                                                     +--------+---------+
                                                              |
                                +------------------------------+------------------------------+
                                |                              |                              |
                       +--------+--------+           +--------+--------+            +---------+--------+
                       |  Value Head     |           |  Action Head     |            |  Target Head    |
                       |  (MLP -> V(s))  |           |  (对每个合法     |            |  (对每个合法    |
                       |                 |           |   动作评分)       |            |   目标评分)     |
                       +-----------------+           +------------------+            +-----------------+
```

### 模块职责分离

| 模块 | 输入 | 输出 | 职责 | 训练阶段 |
|------|------|------|------|---------|
| Instruction Encoder | Hook AST | 语义嵌入 | "这个 hook 做什么"（静态，状态无关） | 预训练，RL 阶段冻结或极小学习率 |
| State Encoder | Counter 值 | 状态嵌入 | "当前局面是什么" | RL 阶段训练 |
| Grounding Attention | 语义嵌入 + 状态嵌入 | 融合表示 | "规则在当前状态下意味着什么" | RL 阶段训练 |
| Policy/Value Heads | 融合表示 | 动作/价值 | 决策 | RL 阶段训练 |

### Instruction Encoder 内部结构

- AST Token Encoder：每个 AST 节点 → token embedding（node_type one-hot + operator + counter_ref_index + const_value → MLP → d 维）
- Self-Attention：token 之间互相关注，捕获 AST 内部结构（如 "这个 if 条件引用了哪个 counter"）
- 输出：每个 hook 的定长语义嵌入

### 超参数

- Instruction Encoder：Self-Attention 2-3 层，d = 64
- Grounding Attention：Cross-Attention 2-3 层，d = 64-128
- 预估参数量：Instruction Encoder ~100K，其余 ~200K，总计 ~300K


---

继续阅读：
- `docs/network/implementation.md` — 当前 `training/network.py` 的实际模块结构
- `docs/network/dropout.md` — Dropout 设计 + train/eval mode 策略
