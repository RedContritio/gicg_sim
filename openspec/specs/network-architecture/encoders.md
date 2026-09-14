---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: network-architecture
subtopic: encoders
---

# Encoders + Pool — 主干结构

> 本 subtopic 锚定 GICG 网络主干(trunk)的 encoder / cross-attention /
> pool 组件契约。共 5 个主组件 + struct_readout 绕路:HookEncoder、
> CounterEncoder、CardEncoder、CrossAttention(× 2 layers)、Pool;
> struct_head 在 C1v7 引入,绕过 cross-attn pool 直通 head。所有组件
> 输出汇入 `global_state`(6·d_model 维)供 head 消费。
>
> Head 部分在 [`./heads.md`](./heads.md)。Loss 在 [`./loss.md`](./loss.md)。

## 1. Scope

本 subtopic 覆盖:

- HookEncoder(Transformer 2L × 4H)消费 `hook_ir` raw int + with-grad 路径
- CounterEncoder(sid + value proj + active mask)消费 `counter_values` +
  `counter_meta`
- CardEncoder(bucket + slot table + count proj)消费 `card_buckets` +
  `enemy_sizes`
- CrossAttention(× 2 layers,bidirectional counter ↔ hook)
- Pool layer:counter_pool / hook_pool / char_skill_pool(via
  `char_skill_refs`)+ card_emb + meta_emb + struct_feat 拼成 global_state
- struct_readout(C1v7):`Linear(66 → d_model)` 绕过 cross-attn 直通

## 2. HookEncoder

### 2.1 SHALL invariants

1. HookEncoder SHALL be a 2-layer Transformer encoder(`n_layers=2`,
   `n_heads=4`,`d=d_model`,FFN inner dim `4d`,batch_first)。
2. HookEncoder SHALL run **with gradient** on training path —
   `train_step` 从 buffer 取 raw tokens 重跑 hook_encoder,SHALL NOT
   feed pre-encoded `hook_emb`(违反此约束 → C1v6 hook-gradient bug
   复发,详 `docs/5_history/network_design_history.md`)。
3. Inference path SHALL use server-cached pre-encoded `hook_emb`(no_grad
   快路径)— per-game cache,详 [`./training-pipeline.md`](./training-pipeline.md)。

### 2.2 结构

```python
HookEncoder(opcode_vocab=16, operand_vocab=2048, token_dim=d_model,
            n_heads=4, n_layers=2, max_ops=128, dropout=cfg.dropout)
```

输入为 `hook_ir (B, N_hooks, max_ops, 5)`，每条指令依次为
`opcode, dst, op1, op2, op3`。

1. `tok = opcode_embed(opcode) + operand_projection(concat(E(dst), E(op1), E(op2), E(op3))) + pos_embed`
   - `E` 为共享操作数词表，空引用 -1 使用保留项，引用 0 使用另一项；`operand_projection` 为无偏置 `Linear(4d, d)`。
   - 字段 SHALL 按角色拼接，SHALL NOT 将四字段嵌入直接求和。
     给字段加固定角色向量后再求和同样不能消除交换对称性，不符合此要求。
   - `pos_embed` 标识指令位置；opcode 0 为 padding。
2. `nn.TransformerEncoder(2 layers, d, 4 heads, FFN=4d, batch_first)`。
3. Mean-pool over non-padding operations → `(B, N_hooks, d)`。
4. `OpLoadImm`（opcode 1）的值 SHALL 在词表查找中被遮蔽，并通过
   `MLP([value/10, sign(value)*log1p(abs(value))])` 加入指令嵌入，保留符号及数值尺度。
   其他操作数仍为离散引用/类型词表，SHALL NOT 一律解释为数值大小。
   canonical定义节点使用独立观察opcode 15，只携带技能/卡牌种类，不携带内部编号。
   这提供数值可学习性，不保证训练后已学会算术或规则语义。
5. 字段投影参数属于模型结构。缺少该参数的旧权重 SHALL 被严格加载拒绝；
   源码兼容指纹随此结构变更，正式训练 SHALL 使用新鲜权重与经验。

## 3. CounterEncoder

### 3.1 SHALL invariants

1. CounterEncoder SHALL filter active slots by `active_slot_mask`,
   SHALL NOT use `counter_values ≠ 0` as filter(B1 修复 invariant)。
2. CounterEncoder SHALL emit `(B, max_active, d) + mask` where
   `max_active = int(active_slot_mask.sum(1).amax())` computed
   **on-device**(C 修复:避免 per-forward GPU↔CPU sync)。
3. Sid embedding SHALL be size `(max_slots=2000, d)`,sid clamp to
   `[0, 1999]`。

### 3.2 结构

```python
CounterEncoder(max_slots=2000, embed_dim=d_model)
```

输入 `counter_values (B, 1832)`, `counter_sids (B, 1832)`, `active_slot_mask (B, 1832)`。

1. `val_emb = value_proj(value.unsqueeze(-1))`
2. `sid_emb = sid_embed(sid.clamp(0, 1999))`
3. `all_emb = val_emb + sid_emb`
4. 按 `active_slot_mask` 排序,取前 `max_active` 个(per-batch)
5. Output:`(B, max_active, d)` + mask

## 4. CardEncoder

### 4.1 SHALL invariants

1. CardEncoder SHALL combine bucket emb + slot emb + count proj as
   `tok + count_emb`,SHALL NOT use `(tok + count_emb) * counts`(E2
   修复:避免数量双重放大)。
2. CardEncoder SHALL apply `mask = counts > 0` then mean-pool over
   nonzero slots。
3. `enemy_size_proj(enemy_sizes)` SHALL be added as residual on pooled
   output(public-info 残差)。

### 4.2 结构

```python
CardEncoder(n_card_slots=80, n_buckets=4, d_model)
```

1. `tok = bucket_emb(b) + slot_emb(s)` — `(n_buckets, n_slots, d)` 静态 table
2. `count_emb = count_proj(counts.unsqueeze(-1))` — count 标量投影
3. `tok_emb = tok + count_emb` — **不乘 counts**
4. `mask = counts > 0`; `tok_emb = tok_emb * mask`; mean pool
5. `+ enemy_size_proj(enemy_sizes)` 残差

## 5. CrossAttention × 2 layers

### 5.1 SHALL invariants

1. CrossAttention SHALL stack exactly **2 layers**(`n_cross_layers=2`,
   d=128, 4 heads, dropout=cfg.dropout)。增减层数 = 架构变更,需 change
   proposal。
2. CrossAttention SHALL be bidirectional `counter_emb ↔ hook_emb`:
   - `c→h`:counter queries hook(`counter_to_hook_attn`)
   - `h→c`:hook queries counter(`hook_to_counter_attn`)
3. Each direction SHALL apply residual + LayerNorm + FFN + LayerNorm。
4. Key-padding mask SHALL come from `~counter_mask` / `~hook_mask`
   respectively。

### 5.2 结构

```python
CrossAttentionBlock(d_model, n_heads=4, dropout=dropout)
```

```python
# c→h
counter_emb = LayerNorm(counter_emb +
    counter_to_hook_attn(counter_emb, hook_emb, hook_emb,
                        key_padding_mask=~hook_mask))
counter_emb = LayerNorm(counter_emb + FFN(counter_emb))

# h→c
hook_emb = LayerNorm(hook_emb +
    hook_to_counter_attn(hook_emb, counter_emb, counter_emb,
                        key_padding_mask=~counter_mask))
hook_emb = LayerNorm(hook_emb + FFN(hook_emb))
```

两层 stacked,输入输出维度 `(B, N, d)` 不变。

### 5.3 已知 saturation 与 struct_readout 绕路

C1v6 batch=64 诊断显示 cross-attn 满熵 — pool 零空间(C18 定理:
mean-pool 集合置换不变,下游 loss 对 `A_{ij}` 内部分布梯度为 0,L2
decay 拖平 Q·K,attention 均匀)。C1v7 不修 cross-attn,改用
`struct_readout`(§7)绕过 pool 提供结构性可见性。CrossAttention 保留
在架构中,但实测 `no_cross` ablation 性能持平(见
`docs/5_history/network_design_history.md::cross_attn_saturation` 章节)。

## 6. Pool → global_state

### 6.1 SHALL invariants

1. Pool layer SHALL emit **6 components** to be concatenated into
   `global_state`:
   - `counter_pool`(masked mean of counter_emb)
   - `hook_pool`(masked mean of hook_emb)
   - `char_skill_pool`(via `char_skill_refs` gather + mask `-1`)
   - `card_emb`(CardEncoder output)
   - `meta_emb`(`meta_proj(meta)`)
   - `struct_feat`(`struct_head(structural_values)`,详 §7)
2. `global_state` SHALL have shape `(B, 6 · d_model)`(d=128 时 = 768)。
3. `char_skill_pool` SHALL use `char_skill_refs` gather + mask
   `(refs ≥ 0)` masked mean。SHALL NOT collapse to single global mean
   pool(避免 C18 pool 零空间)。

### 6.2 实现

```python
counter_pool = (counter_emb * counter_mask).sum(1) / counter_mask.sum(1).clamp(min=1)
hook_pool    = (hook_emb    * hook_mask   ).sum(1) / hook_mask.sum(1)   .clamp(min=1)

# char_skill_pool:gather → mask -1 → masked mean
#   refs:    (B, 2, 6, 10) long, 值 ∈ {-1, 0..n_active-1}
#   gathered = hook_emb[refs.clamp(0)]        (B, 120, d)
#   valid    = (refs >= 0)                    (B, 120)
#   pool     = sum(gathered * valid) / sum(valid).clamp(min=1)
char_skill_pool = masked_mean(gather(hook_emb, char_skill_refs), mask=refs≥0)

card_emb     = card_encoder 输出
meta_emb     = meta_proj(meta)
struct_feat  = struct_head(structural_values)  # (B, d)

global_state = cat([counter_pool, hook_pool, char_skill_pool,
                    card_emb, meta_emb, struct_feat])  # (B, 6d)
```

## 7. struct_readout(C1v7)

### 7.1 SHALL invariants

1. `struct_head` SHALL be `nn.Linear(66, d_model)` consuming
   `counter_values` gathered by structural pinned sids(HP/Energy/Alive/
   Active/dice/alive_count 的 66 个固定位)。
2. struct_readout SHALL bypass CounterEncoder + CrossAttention + pool —
   `struct_feat` 直接 cat 到 `global_state`。
3. Engine 侧 SHALL pin structural sids stable across games:
   - HP/Energy/Alive/Active/dice/alive_count 每局 sid 稳定在 0..65
   - Phantom counters(value=max=min=0)填 unbound 的 char 槽,让 sid 跨
     `team_size` 稳定(e.g. sid=5 永远是 "HP P0 c5")
   - Mechanical counters(shields/buffs/summons/attachments)仍每局
     shuffle,保持反 ID
   - `interp.MaxChars = 6` 匹配 `ObsMaxChars`
   - bucket 内按 sid 排序,HP 落 bucket 首位(obs[0] = HP P0 c0)
4. Network 侧 `compute_structural_obspos` 在
   `training/framework/structural.py` 计算 gather 索引;sanity 校验由
   `tools/sanity_sid_pin.py` 提供。

### 7.2 设计契约

struct_readout 解决 C1v6 cross-attn pool 零空间下 value/policy head
"看不到单个 counter 值" 的根因。反 ID 原则在此精炼为:**"无法从 DSL
hook 推理的量必须固定"** — HP / energy 等基础结构量是 hook 无法 carry
的语义,必须 sid pin。Mechanical counters(shield / buff / summon /
attachment)可由 hook tokens 推理(reaction-trigger / on_apply 等),
继续 shuffle。

## 8. 尺寸与参数

| 参数 | 值 |
|---|---|
| `d_model` | 128 |
| `n_cross_layers` | 2 |
| `n_heads` | 4 |
| `HookEncoder n_layers` | 2 |
| `n_counter_slots` | 1832 |
| `n_hooks` | 900 |
| `max_tokens_per_hook` | 120 |
| `max_actions` | 2048 |
| 总参数 | ~1.82 M |
| L2 regularize | 1.81 M(`dim ≥ 2`)|
| Skip L2 | 11.9 k(biases + LayerNorm,详 [`./loss.md`](./loss.md))|

## 9. Cross-reference

- **Obs source**:[`./obs.md`](./obs.md) — encoder 消费的字段 shape
- **Head consumption**:[`./heads.md`](./heads.md) — `global_state`
  如何被 value / delta / policy 三头消费
- **Loss**:[`./loss.md`](./loss.md) — L2 跳过 bias/LN(防 LN scale
  塌缩)/ entropy / delta aux 与 struct_readout 的耦合
- **Engine code**:`gicg_engine/interp/structural.go`(sid pinning) +
  `training/framework/structural.py::compute_structural_obspos` +
  `tools/sanity_sid_pin.py`
