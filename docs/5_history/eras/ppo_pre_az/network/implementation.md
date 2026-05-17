# 网络架构 — 当前实现

> 本文是 `docs/network/README.md` 的延续。前置 `docs/network/README.md` 描述早期 plan
> 用的术语 (Instruction Encoder / Grounding Attention)；本文描述 shipped
> 代码 (`training/network.py`) 中实际的模块名和结构。

## 5. 当前实现（training/network.py）

上文第 1-4 节所用术语早于当前代码。已发布的架构在设计思路上相似，但模块名有所不同。本节描述 `training/network.py` 中的实际内容。

### 模块对照表

| 文档术语 | 代码类名 |
|----------|------------|
| Instruction Encoder | `HookEncoder` |
| State Encoder | `CounterEncoder` |
| Hand Encoder | `CardEncoder` |
| Grounding Attention | `CrossAttentionBlock` |
| Policy Head | `ActorCritic.state_proj` + 指针网络点积（见 §5.6） |
| Value Head | `ActorCritic.value_head` |
| Network wrapper | `ActorCritic` |
| RL agent（模型 + 优化器） | `Agent` |

### `HookEncoder`（静态，每个 episode 编码一次）

```python
class HookEncoder(nn.Module):
    def __init__(self, vocab_size=256, token_dim=64, n_heads=4, n_layers=2, max_tokens=120):
        self.token_embed = nn.Embedding(vocab_size, token_dim)
        self.value_proj = nn.Linear(1, token_dim)
        self.pos_embed = nn.Embedding(max_tokens, token_dim)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=token_dim, nhead=n_heads, dim_feedforward=token_dim * 4,
            batch_first=True, dropout=0.0,
        )
        self.transformer = nn.TransformerEncoder(
            encoder_layer, num_layers=n_layers,
            enable_nested_tensor=False,    # MPS 兼容性
        )
```

`enable_nested_tensor=False` 是 MPS 所必须的——快速路径使用的
`aten::_nested_tensor_from_mask_left_aligned` 在 MPS 上未实现。

输出：`(batch, n_active_hooks, token_dim)`。在 agent 上缓存，
同一 episode 的所有步骤复用。

### `CounterEncoder`（动态，稀疏）

仅编码非零的 counter 槽——在任意给定步骤中，1832 个槽中的大多数都为零。
返回 `(batch, max_active, embed_dim)` 以及一个布尔掩码。
每个槽使用 `value_proj(value) + sid_embed(sid)` 进行编码。

稀疏性至关重要：cross-attention 的开销随活跃 counter 数量（约 30）而不是总槽数（1832）线性增长。

### `CrossAttentionBlock`（每层）

双向注意力：counter 关注 hook，然后 hook 关注 counter。
包含两个 MultiheadAttention 模块 + 两个 FFN + 四个 LayerNorm +
残差连接 + 三处 dropout（注意力权重、注意力输出、FFN 中间层）。

```python
class CrossAttentionBlock(nn.Module):
    def __init__(self, d_model=64, n_heads=4, dropout=0.1):
        self.counter_to_hook = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.hook_to_counter = nn.MultiheadAttention(d_model, n_heads, dropout=dropout, batch_first=True)
        self.attn_drop_c2h = nn.Dropout(dropout)
        self.attn_drop_h2c = nn.Dropout(dropout)
        self.counter_ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model), nn.Dropout(dropout),
        )
        self.hook_ffn = nn.Sequential(
            nn.Linear(d_model, d_model * 4), nn.ReLU(), nn.Dropout(dropout),
            nn.Linear(d_model * 4, d_model), nn.Dropout(dropout),
        )
        self.norm1 = nn.LayerNorm(d_model)  # ... 共 4 个 norm
```

默认 2 层。在早期训练中，第 1 层有时会收缩为近乎均匀的注意力分布（这是堆叠 Transformer 编码器的标准"注意力收敛"现象）。Dropout 的作用是通过阻止第 1 层退化为恒等映射来缓解这一问题。

### `CardEncoder`（动态，稀疏）

将手牌/牌库/弃牌堆的卡牌桶计数（4 × 80 个卡牌槽）以及
对手手牌/牌库大小编码为单个 `d_model` 向量。每个 episode 的
`CardPerm` 会打乱每个卡牌槽的位置语义，防止网络记忆绝对槽索引。
编码器为每个（桶, 槽）构建可学习的 `bucket_emb + slot_emb + count_proj`，
对非空条目进行池化，然后加上两个对手大小标量的投影。

### `ActorCritic`（前向传播，指针网络策略头）

```python
def forward(self, counter_values, counter_sids, hook_emb_cached,
            hook_mask, card_buckets, enemy_sizes, meta,
            action_refs, legal_mask):
    counter_emb, counter_mask = self.counter_encoder(counter_values, counter_sids)

    # 双向 cross-attention（counters ↔ hooks）
    hook_emb = hook_emb_cached
    for layer in self.cross_layers:
        counter_emb, hook_emb = layer(counter_emb, hook_emb, counter_mask, hook_mask)

    counter_pool = masked_mean(counter_emb, counter_mask)
    hook_pool    = masked_mean(hook_emb,    hook_mask)
    card_emb     = self.card_encoder(card_buckets, enemy_sizes)
    meta_emb     = self.meta_proj(meta)

    # 策略状态去掉 hook_pool，以避免与 action_emb 来源相同导致的退化
    #（见下文）。价值头保留完整信息。
    policy_combined = torch.cat([counter_pool, card_emb, meta_emb], dim=-1)
    value_combined  = torch.cat([counter_pool, hook_pool, card_emb, meta_emb], dim=-1)
    state_vec = self.state_proj(policy_combined)

    # 指针网络动作嵌入，按合法槽：
    #   Skill / Card → 取 cross-attn 后的 hook_emb[hook_idx]
    #   Switch       → char_slot_emb[char_idx]（6 个可学习槽）
    #   EndTurn      → self.end_turn_emb（共享常量）
    action_emb = build_action_emb(action_refs, hook_emb,
                                  self.char_slot_emb, self.end_turn_emb)
    action_emb = self.action_emb_norm(action_emb)

    logits = (state_vec.unsqueeze(1) * action_emb).sum(-1)
    logits = logits.masked_fill(~legal_mask, -1e9)
    value  = self.value_head(value_combined).squeeze(-1)
    return Categorical(logits=logits), value
```

关键设计要点：

- **指针网络，而非固定 Linear**：旧的 `policy_head = Linear(→ max_actions)`
  是基于位置的——槽 K 在不同步骤之间没有稳定的语义，因为合法动作的排列每步都会变化。
  现在每个合法槽获得一个*语义*嵌入（技能/卡牌使用 hook，切换使用每槽可学习向量，
  结束回合使用可学习常量），logit 为与 `state_vec` 的点积。
- **cross-attention 后的 hook_emb**：动作嵌入取自双向注意力*之后*，
  因此每个 hook 已经与当前 counter 状态完成了上下文化（"当前状态下的枪"而非"抽象的枪"）。
  这赋予策略头类似 Q 函数的表达能力，而不是纯双塔结构。
- **策略状态去掉 hook_pool**：否则 `state_vec` 和 `action_emb` 都来自同一个 `hook_emb` 张量，
  使点积部分退化为 ⟨hook_mean, hook_i⟩。我们保留 `counter_pool`
  （它已经通过 `counter_to_hook` 关注了 hook）、`card_emb` 和 `meta_emb`，
  但不保留 `hook_pool`。`value_head` 仍然看到完整的 4·d 拼接——
  价值侧无需担心点积退化。

默认配置：
```
d_model        = 64
n_cross_layers = 2
n_heads        = 4
dropout        = 0.1
```

总参数量约 510K（不含 CardEncoder 和指针网络新增部分）。
