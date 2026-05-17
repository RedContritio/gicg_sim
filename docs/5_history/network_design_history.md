# Network design 历史推导(P1-T2 archived)

> 本文档合并自:
> - `docs/1_specs/network/design.md`(原架构设计推导,~220 行)
> - `docs/1_specs/network/current.md` L447-472(C1v6 前六项修复 + 下一步)
>
> 当前 shipped 网络规约见 `openspec/specs/network-architecture/` —
> 本文件保留作历史复盘(C1v0-C1v7 演化推理 / 设计 tradeoff /
> NOT SHIPPED 组件)。后续 P1-T8 写 paradigm dossier 时可 reference
> 本文档作为 AZ paradigm 的 architecture/ subtopic 来源。
>
> 章节锚点(便于 spec 跨 ref):
> - `#charencoder-not-shipped` — CharEncoder 设计但未 shipped
> - `#cross_attn_saturation` — CrossAttention 满熵 / pool 零空间诊断
> - `#policy_head_pointer_net_evolution` — 指针网络策略头设计
> - `#c1v6_pre_fixes` — C1v6 前六项 bug 修复表
> - `#stale_weights_ok` — Stale weights 容忍设计
>
> ---

## 第一部分:网络架构(设计意图,2026-04-18 原始 design.md)

> 相关决策:`decisions.md` D3(共享主干 + 多头),
> D8(基于特征的嵌入,可配置维度),D11(牌组构建器
> 作为未来的头部)。
>
> ⚠️ **本部分是设计意图,部分组件未 shipped**。shipped 实际结构请读
> `openspec/specs/network-architecture/`。两者冲突时以 OpenSpec 为准。
>
> 各节已标注 SHIPPED / NOT SHIPPED 状态(2026-04-18 复查)。

### 整体结构

```
Observation (perspective-specific, already info-set level)
         │
         ▼
┌─────────────────────┐
│    Shared Trunk     │
│                     │
│  counter_encoder    │  (counter values + slot features)
│  hook_encoder       │  (hook DSL tokens, already cached per-game)
│  card_encoder       │  (hand/deck/discard counts + card features)
│  char_encoder       │  (character features via MLP on DSL metadata)
│  cross_attention    │  (bidirectional counter ↔ hook)
│  pool               │  (context-aware attention-weighted pool)
└──────────┬──────────┘
           │
           ▼  d_model-dim pooled state vector
           │
    ┌──────┴───────┬─────────────┐
    │              │             │
    ▼              ▼             ▼
┌─────────┐   ┌─────────┐   ┌──────────┐
│ value   │   │ policy_ │   │ policy_  │
│ head    │   │ tactical│   │ deckbuild│  ← deferred (D11)
└─────────┘   └─────────┘   └──────────┘
  (scalar)     (MAX_ACTIONS)   (future)
```

**共享组件**(主干 + 价值头)学习通用游戏知识。**阶段专用头部**(战术 / 未来牌组构建)将主干输出映射到适合当前阶段的动作分布。

### 核心原则:单一网络,共享知识

这是 D3 决策。价值头学习"从当前状态出发的预期最终游戏结果",与状态所处的阶段无关。在战术对局中,它看到的是对局中期局面;在未来的牌组构建阶段,它看到的是部分构建完成的牌组。两者都被训练为预测相同的目标(最终游戏结果 z)。

**这就是跨阶段知识迁移的方式**:价值头在大量具有不同队伍构成的战术对局上训练后,隐式地编码了"这种队伍构成倾向于获胜"的信息。当未来的牌组构建器在对部分牌组进行 MCTS 搜索时查询价值头,便可以免费获得这些知识。

### 主干组件

#### CounterEncoder [SHIPPED, C1v7 扩展]

- 输入:计数器值的扁平数组(HP、能量、状态标志等)
- 输出:每个计数器的嵌入张量
- 当前实现:`sid_embed` 表(每槽大小)+ 值投影。
- **C1v7 新增**:structural counter sids (HP/energy/alive/active/dice/alive_count) pin 到固定位置 0..65;mechanical 仍 shuffle。struct_head 直接从 66 固定位读出绕过 pool。详见 OpenSpec `encoders.md` struct_readout section。

#### HookEncoder(按局缓存) [SHIPPED]

- 输入:来自静态观测的 hook DSL 令牌
- 输出:每个 hook 的嵌入,在游戏开始时缓存一次(hook 在游戏内不会改变)
- 从 PPO 网络保留。

#### CardEncoder [SHIPPED, 但 card_feature_proj 未 shipped]

- 输入:手牌/牌库/弃牌堆计数分桶
- 输出:池化后的卡牌池嵌入
- ✅ 分桶计数路径已 shipped
- ❌ **`card_feature_proj` MLP 从未实施**(D8 的 per-card feature 嵌入)。shipped 代码只用分桶计数 + bucket_emb/slot_emb,没有从 card ref 生成特征向量的路径。
- 如需 1000 张牌的泛化,D8 的特征路径仍是可选升级。

#### <a id="charencoder-not-shipped"></a>CharEncoder [NOT SHIPPED]

- ❌ **从未实施**。shipped 代码没有 CharEncoder 模块,角色信息通过两条路径进入:
  1. 结构性 char state (HP/Energy/Alive/Active) 走 C1v7 的 struct_head 固定位置(见 OpenSpec `encoders.md`)
  2. 字符相关的 hook tokens 走 HookEncoder
- 未来若扩展到 100-300 角色池,再评估是否需要 CharEncoder 或用 hook tokenization 扩展。

#### <a id="cross_attn_saturation"></a>CrossAttention + pool [SHIPPED, 但功能事实上零贡献]

- 计数器嵌入与 hook 嵌入之间的双向注意力,从 PPO 网络保留。
- 在注意力权重、注意力输出、FFN 内层上应用 Dropout。
- 注意力池化产生单个 d_model 向量作为主干输出。
- ⚠️ **C1v7 诊断**:pool 零空间 (C18 定理) 使 attention 权重无梯度,L2 decay 拖平 Q·K,attention 均匀。删除 cross-attn 性能持平。保留在架构中但不再是主要信号路径。详见 OpenSpec `encoders.md::CrossAttention`。

### 头部

#### 价值头(共享) [SHIPPED]

```python
class ValueHead(nn.Module):
    def forward(self, pooled: Tensor) -> Tensor:
        # pooled: (B, d_model)
        # return: (B,) scalar in [-1, 1]
        x = self.mlp(pooled)
        return torch.tanh(x)
```

- 输出:[-1, 1] 范围内的标量,表示从行动方视角出发的预期游戏结果
- 训练损失:与终局游戏结果 `z`(±1 或 0)的 MSE
- 在所有阶段共享(当前为战术阶段,未来扩展至牌组构建阶段)
- 无论哪个阶段生成了该状态,每次经验回放缓冲区采样都会训练该头部

#### <a id="policy_head_pointer_net_evolution"></a>策略头——战术 [SHIPPED]

```python
class TacticalPolicyHead(nn.Module):
    def forward(self, pooled, action_refs, action_features, mask) -> Tensor:
        # pooled: (B, d_model)
        # action_refs: (B, MAX_ACTIONS, n_ref_fields)
        #              e.g. (kind, skill_ref, card_ref, dice_combo_8d)
        # action_features: (B, MAX_ACTIONS, d_model) action embeddings
        # mask: (B, MAX_ACTIONS) bool
        # return: (B, MAX_ACTIONS) logits
        q = pooled.unsqueeze(1)                   # (B, 1, d_model)
        logits = (q * action_features).sum(-1)    # pointer-net score
        logits = logits.masked_fill(~mask, -inf)
        return logits
```

- 指针网络风格:池化向量关注由 hook 嵌入(代表游戏效果)+ 骰子组合特征(代表费用)计算得到的每个动作嵌入
- 输出:MAX_ACTIONS 上的 logits
- 训练损失:与 MCTS 访问次数分布的交叉熵 `CE(softmax(logits), visits_softmax)`
- 遮盖:非法动作(超出当前合法动作数量的部分)被遮盖为 `-inf`,使其在 softmax 后概率为 0

#### 动作特征计算

每个合法动作由一个进入策略头指针计算的特征向量表示:

```python
action_feature = (
    hook_embeddings[action_hook_id]          # game effect
    + dice_combo_proj(dice_combo_8d)         # payment structure
    + target_proj(target_char_embed)         # target (if applicable)
)
```

- `hook_embeddings`:从每局游戏缓存的 hook 编码器输出中查找(保留自 PPO 方案)[SHIPPED]
- `dice_combo_proj`:MLP `(8 → d_model)`,编码骰子分解向量 `[omni, fire, ice, water, electro, geo, grass, elem7]` [SHIPPED]
- `target_proj`:若动作指向特定角色,则从 CharEncoder 输出中查找目标角色的嵌入 [NOT SHIPPED] — shipped 用 `char_slot_emb[char_idx]` (学习的 per-slot embedding) 替代,见 OpenSpec `heads.md::Policy Head`

对于 MVP(AP 作为万能骰子),骰子组合向量始终为零或极简——`dice_combo_proj` 退化为约零残差。在真实骰子系统上线之前,不会产生行为变化。

#### 策略头——牌组构建(延迟,D11)

未来扩展的占位符:

```python
class DeckbuildPolicyHead(nn.Module):
    # Same structure as tactical head, but action space is
    # "pick card X from pool" or "done". Action embeddings come
    # from card_encoder's per-card features.
    ...
```

**MVP 约束**:`ActorCritic.forward` 必须保持足够的可插拔性,使得添加此头部只需几行代码,无需重构主干或现有头部。

### 训练损失(原 design.md,与 OpenSpec loss.md 差异)

原始 design.md 提出的简化 loss:

```
loss = value_loss + policy_loss + weight_decay
```

- `value_loss = mean((v_net(s) - z)²)` — 与最终游戏结果的 MSE,z ∈ {-1, 0, +1}
- `policy_loss = mean(-sum(visits_softmax * log_softmax(logits)))` — 与 MCTS 访问次数分布的交叉熵
- `weight_decay = 1e-4 * sum(params²)` — L2 正则化

无熵奖励(AZ 不使用——探索来自 MCTS 根节点的 Dirichlet 噪声,而非策略熵)。

无价值损失系数(标准 AZ 使用 1.0)。

**Shipped 偏离**:实际 5 分量(+ entropy + delta aux),L2 跳过 `dim<2` 防 LN 塌缩(修复 A)。详 OpenSpec `loss.md`。

### 观测接口

观测在引擎层面已经是**视角正确**的(参见 `gicg_engine/observation.go::BuildDynamicObs`):
- 己方:手牌内容、牌库内容、弃牌堆内容、角色计数器
- 对方:弃牌堆内容(公开信息)、**仅手牌数量**、**仅牌库数量**、角色计数器

这意味着网络**原生**地在信息集观测上运行——Python 端无需进行遮盖或视角变换。

观测维度**在运行时从引擎查询**,而非硬编码:
- `GameGetStaticObsSize()` — 计数器槽位数量等
- `GameGetDynamicObsSize()` — 每步观测大小
- 网络在创建时读取这些值

嵌入表按**物理上限**大小设置(`MAX_CARDS=2048`、`MAX_HOOKS=8192`、`MAX_CHARS=512`),以便在不进行架构变更的情况下适应未来的增长。特定游戏中实际使用的词表是引擎提供 ID 所索引的子集。

### 前向兼容约定

MVP 网络实现必须:
1. 使用 `nn.ModuleDict` 或等价结构管理策略头,使添加新头部变得简单
2. 不硬编码 `MAX_ACTIONS = 64`——必须从配置中读取
3. 不硬编码计数器 / hook / 卡牌 / 角色维度——必须在构建时从引擎读取
4. `forward()` 接受 `phase` 参数,分派至正确的策略头(MVP:始终为 "tactical")
5. 价值头输出经 tanh 限制在 [-1, 1],使 ±1 的 CE 目标可达,避免 logit 爆炸

违反上述任何一条都将在添加牌组构建(D11)或真实骰子(D7)时需要重构。

### 相较当前 PPO 网络的变更

删除:
- `RewardNormalizer` — 无需归一化奖励(仅终局 ±1)
- 每环境缓存(`_cache_*`)— AZ 执行单状态前向传播,而非批量 rollout
- `sample_action` 方法 — AZ 使用 `forward` → argmax 或访问次数采样,而非 PPO 的随机采样
- `value_only` 方法 — AZ 在叶节点评估时始终同时前向传播两个头部
- 所有 PPO 专用损失项(熵、KL、裁剪)

保留:
- `encode_static` — 每局游戏的 hook 嵌入缓存
- 主干编码器和交叉注意力结构
- 策略头的指针网络模式

新增:
- CardEncoder 中的 `card_feature_proj` 残差
- `CharEncoder`,替代原先隐式的"角色即计数器组"模型
- 用于动作特征的 `dice_combo_proj` MLP
- `forward` 中的多头分派

净变化:约删除 200 行,新增 300 行。主干约 70% 复用自 PPO 实现。

---

## 第二部分:C1v6 前的六项修复 + 下一步(原 current.md L447-472)

### <a id="c1v6_pre_fixes"></a>C1v6 前的六项修复摘要

当前快照对应以下 bug 修复之后的状态。详见 `c1_postmortem.md` 的 G3 扰动诊断和 `review_internal.md`:

| 修 | 之前 | 现在 |
|---|---|---|
| hook gradient | `game_static` 存 pre-encoded `hook_emb`(no_grad) | 存 raw tokens,train_step 时 `hook_encoder` 重跑 with grad |
| A | L2 decay 所有参数(LayerNorm weight 塌缩) | skip `dim < 2` 的 params(bias + LN) |
| B1 | CounterEncoder 按 `value ≠ 0` 过滤(丢破盾/解冻/归零瞬间)| 按 `active_slot_mask` (min/max 判真假)过滤 |
| C | `max_active = tensor.max().item()` 每 forward 1 次 sync | `int(amax.clamp_min(1))` on-device,一次 sync |
| D1 | `state_vec = [counter, card, meta]` 3·d(policy 不看 hook 全局) | `state_vec = [counter, hook, card, meta]` 4·d,和 value 对称 |
| E2 | `(tok + count_emb) * counts`(数量双重放大) | `tok + count_emb`,mean pool on count>0 |
| F | `HookEncoder` dropout 硬编码 0 | 构造器接受 `dropout` 参数(当前 config 仍 0) |

详细的 bug 诊断过程、梯度流证据、权重塌缩验证见 `review_internal.md` 第 3 节(已归入 5_history/reviews/)。

### 下一步(C1v6 验证;已 superseded by C1v7)

修复后首次真正训练 hook_encoder 的 run。当时关键验证:

- 训练稳定性(C1v6 完成时 loss 曲线)
- `tools/probe_numeric_sensitivity.py` 对 final_champion 扰动:hook token 扰动是否首次让 value/policy 响应
  - 响应 → "反 ID + hook tokenization" 假设首次被公平测试;G1 领域随机化实际生效
  - 仍麻木 → 升级 D2(state→hook attention pool)或重审 HookEncoder 架构;见 `memory/project_d2_state_hook_attention.md`

**复盘**:C1v6 验证后 cross-attn 仍满熵(C18 pool 零空间),D2 方案 (state→hook attention pool) 被 C1v7 struct_readout 取代——更直接绕过 pool,而不是再设计新 attention 层。

---

## 第三部分:Stale weights 设计契约

### <a id="stale_weights_ok"></a>Stale weights 容忍

AZ 异步采样架构下,worker 见到的 weights 比 trainer 当前 weights 落后 10-30 局是常态,不影响 AZ 收敛(`z` / `pi_mcts` 都是 on-policy to worker 当时 weights)。这与 PPO 严格 on-policy 栈(每个 worker 收到的 weights 必须是 trainer 最新)对比鲜明。

OpenSpec invariant:见 `training-pipeline.md::stale-weights-容忍`。
