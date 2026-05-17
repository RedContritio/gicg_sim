# 当前网络结构（shipped 状态）

> **MOVED to `openspec/specs/network-architecture/`**（2026-05-15，P1-T2）
>
> 本文档内容已迁到 OpenSpec（SHALL 语言），按 5 subtopic 拆分:
> - [Obs schema](../../../openspec/specs/network-architecture/obs.md)
> - [Encoders](../../../openspec/specs/network-architecture/encoders.md)
> - [Heads](../../../openspec/specs/network-architecture/heads.md)
> - [Loss](../../../openspec/specs/network-architecture/loss.md)
> - [Training pipeline](../../../openspec/specs/network-architecture/training-pipeline.md)
> - 顶层 spec:[network-architecture/spec.md](../../../openspec/specs/network-architecture/spec.md)
>
> Design 推导 + C1v6 修复历史 → `docs/5_history/network_design_history.md`
>
> 本文件保留至 P1++（`docs/1_specs/` 整体清理）；**只读**。

---

> 2026-04-18 更新。本文档是**当前 shipped 代码的结构快照**，包括 C1v7 架构（结构性 sid pinning + phantom counters + per-slot struct_readout），在 C1v6 aux loss 和 hook-gradient 修复基础上叠加。
>
> 对应设计意图请读 [`network_design.md`](network_design.md)（已标注每节 SHIPPED/NOT SHIPPED）。若两者冲突以本文档为准；`CharEncoder` / `card_feature_proj` 等设计组件从未 shipped，见 design 侧标注。
>
> 对应 run：C1v7（`az_c1v7`），首个"反 ID + 结构性引用分离"架构公平验证通过的训练（argmax vs mcts_200 = 45%）。

## C1v7 结构性改动速览 (2026-04-18)

**根因**：C1v6 cross-attn pool 零空间（C18 定理）— mean pool 是集合置换不变, 下游 loss 对 A_{ij} 内部分布梯度为 0, L2 decay 把 Q·K 拖平, attention 均匀, value head 无法"看到"单个 counter 的值。

**修复**：不修 cross-attn, 改引用结构 + 绕过 pool:

1. **结构性 sid pinning** (engine 侧):
   - 反 ID 原则精炼: "无法从 DSL hook 推理的量必须固定". HP/Energy/Alive/Active/dice/alive_count 每局 sid 稳定在 0..65.
   - Phantom counters (value=max=min=0) 填 unbound 的 char 槽, 让 sid 跨 team_size 稳定 (e.g. sid=5 永远是 "HP P0 c5").
   - Mechanical counters (shields/buffs/summons/attachments) 仍每局 shuffle, 保持反 ID.
   - interp.MaxChars 3→6 匹配 ObsMaxChars.
   - bucket 内按 sid 排序, HP 落在 bucket 首位 (obs[0]=HP P0 c0).

2. **struct_readout** (network 侧):
   - `struct_head = Linear(66 → d_model)` 直通 value/policy/delta head, **绕过 CounterEncoder + CrossAttention + pool**.
   - `policy_combined = cat(counter_pool, hook_pool, card_emb, meta_emb, struct_feat)` 维度从 4d 变 5d.
   - CounterEncoder + CrossAttention + pool 仍在原位处理 mechanical counters + hooks, 但实测对 value 贡献小 (no_cross smoke 删 cross_layers 性能持平).

相关: `gicg_engine/interp/structural.go`, `training/framework/structural.py::compute_structural_obspos`, `tools/sanity_sid_pin.py`.

---

---

## 总览

```
Static obs (1×/game, 221KB)        Dynamic obs (1×/step, 8KB)
 ├─ counter_meta (1832, 3)         ├─ meta (3,)
 │    [min, max, shuffled_sid]     ├─ counter_values (1832,)
 └─ hook_tokens (900, 120, 2)      ├─ card_buckets (4, 80)
      [token_type, token_value]    └─ enemy_sizes (2,)

Per-decision:
 ├─ action_refs (N_act, 3)  [kind, hook_idx, char_idx]
 └─ action_payments (N_act, 8)  dice combo
```

```
                        ↓↓↓
┌─────────────────────────────────────────────────────────────┐
│                      Trunk (encoders)                       │
│                                                             │
│  HookEncoder (Transformer 2L × 4H, d=128, dropout from cfg) │
│   ├─ token_embed(types) + value_proj(value) + pos_embed     │
│   ├─ 2-layer transformer                                    │
│   └─ mean-pool non-pad tokens → (N_hooks, d) 带 grad        │
│                                                             │
│  CounterEncoder                                             │
│   ├─ value_proj(value) + sid_embed(sid)                     │
│   ├─ mask = active_slot_mask (min≠0 or max≠0)               │
│   └─ sort + truncate to max_active → (M_active, d) + mask   │
│                                                             │
│  CardEncoder                                                │
│   ├─ bucket_emb + slot_emb + count_proj(count)              │
│   ├─ mean-pool nonzero slots                                │
│   └─ + enemy_size_proj(enemy_sizes) → (d,)                  │
│                                                             │
│  meta_proj(meta) → (d,)                                     │
└─────────────────────────────────────────────────────────────┘
                        ↓↓↓
┌─────────────────────────────────────────────────────────────┐
│  CrossAttention × 2 layers (d=128, 4 heads, dropout=0.1)    │
│   counter_emb ↔ hook_emb 双向融合 + FFN + LayerNorm         │
└─────────────────────────────────────────────────────────────┘
                        ↓↓↓
         counter_pool, hook_pool, char_skill_pool, card_emb, meta_emb
                        ↓↓↓
  struct_feat = Linear(66→d)(counter_values gathered by structural sid)
                        ↓↓↓
   global_state = cat(counter_pool, hook_pool, char_skill_pool,
                      card_emb, meta_emb, struct_feat)
                                                     (6·d = 768)
                        ↓↓↓
        ┌────────────────────────┬──────────────────────────────┐
        │                        │                              │
┌───────────────┐     ┌──────────────────────────────────────┐
│  VALUE HEAD    │     │  POLICY HEAD (pointer-net)           │
│                │     │                                      │
│ MLP (6d→2d→1)  │     │  state_vec = state_proj(6d→2d→d)    │
│ tanh → [-1,1]  │     │                                      │
│     ↓          │     │  action_emb[a]:                     │
│  value (B,)    │     │   ├─ SKILL/CARD:                    │
└───────────────┘     │   │   hook_emb[hook_idx] (post xattn)│
                      │   ├─ SWITCH:                         │
                      │   │   char_slot_emb[char_idx]        │
                      │   ├─ END_TURN:                       │
                      │   │   learned const vec              │
                      │   └─ + dice_combo_proj(payment)      │
                      │       + LayerNorm                    │
                      │                                       │
                      │  logit[a] = ⟨state_vec, action_emb[a]⟩│
                      │   ↓                                   │
                      │   logits (B, N_act)                  │
                      └──────────────────────────────────────┘
```

---

## 输入

### Static obs (每局一次, 221,496 个值)

从 `GameGetStaticObs` 拿到的扁平 int 数组。Python 侧按如下切分：

- **counter_meta**: `(n_counter_slots=1832, 3)`
  - 列 0: `min`（counter 下限，静态）
  - 列 1: `max`（counter 上限，静态）
  - 列 2: `shuffled_sid`（per-game shuffled ID，agent 看不到稳定槽位语义）
  - 衍生 `active_slot_mask = (min≠0 or max≠0)`：该 slot 是否承载真实 counter

- **char_skill_refs**: `(2, ObsMaxChars=6, ObsMaxSkillsPerChar=10)`
  - 每 `(p, c, s)` 存该槽位第 `s` 个技能的 canonical `on_skill_use` hook 在 active hook 列表中的位置，或 `-1` 表示空 slot。
  - 位置 `(p, c)` 结构性编码 owner；物理 slot `s` 通过 `SkillSlotPerm[p][c]` 每 (p, c) 独立 Fisher-Yates 洗（anti-position-ID，类比 per-char counter sid 洗的角色）。
  - 前向用 `gather(hook_emb, refs)` 拉取每 slot 的技能表示；`-1` 处 mask 掉。网络对对方技能有**显式**可见性，不用靠 legal_actions 相关性学 skill_id → owner 映射。
  - Gather 目标就是 pointer-net 策略头给 SKILL 动作用的同一个 canonical hook embedding — 动作选择和观测侧表示对齐。

- **hook_tokens**: `(n_hooks=900, max_tokens_per_hook=120, 2)`
  - 每 hook 一行 token 序列，长度 120（padded 0）
  - 列 0: `token_type`（0=pad, 1-255 词汇表）
  - 列 1: `token_value`（数值字面量时是数字本身；其他 token 为 0）

### Dynamic obs (每步一次, 2,157 个值)

从 `GameGetDynamicObs(player_perspective)`：

- **meta**: `(3,)` — `[phase, round, is_my_turn]`
- **counter_values**: `(1832,)` — 视角正确（己方在前，对方在后）
- **card_buckets**: `(4, 80)` — 4 个桶 × 80 种卡：own hand / own deck / own discard / enemy discard
- **enemy_sizes**: `(2,)` — 对手手牌数、牌堆数（公开信息）

### 每决策（合法动作列表）

- **action_refs**: `(max_actions=2048, 3)` — 每行 `[kind, hook_idx, char_idx]`，非合法位 kind=END_TURN 占位
  - `kind ∈ {SKILL=0, CARD=1, SWITCH=2, END_TURN=3}`
  - `hook_idx`: 对 SKILL/CARD 指该动作的典型 hook（e.g. on_skill_use 的 hook 在 hook_emb 里的位置），其他 = -1
  - `char_idx`: 对 SWITCH 指目标角色槽位，其他 = -1
- **action_payments**: `(max_actions, 8)` — 每行 8 维骰子支付组合 `[omni, fire, ice, water, electro, geo, grass, slot7]`

---

## 网络组件

### HookEncoder

```python
HookEncoder(vocab_size=256, token_dim=d_model, n_heads=4, n_layers=2,
            max_tokens=120, dropout=cfg.dropout)
```

输入 `(B, N_hooks, max_tokens)` 的 tokens + mask。流程：

1. `tok_emb = token_embed(types.clamp(0,255)) + value_proj(value) + pos_embed`
   - `token_embed`: `nn.Embedding(256, d)` — token 类型 embedding
   - `value_proj`: `nn.Linear(1, d)` — **标量投影**，让数值 token 天然有序关系先验（`value_proj(2)` 和 `value_proj(3)` 线性相邻）
   - `pos_embed`: `nn.Embedding(120, d)`
2. `nn.TransformerEncoder(2 layers, d, 4 heads, FFN=4d, batch_first)`
3. Mean-pool over non-pad tokens → `(B, N_hooks, d)`

**关键**：训练路径里每次 `forward_batch` 都调用 HookEncoder（输入来自 replay buffer 存的 raw tokens）。推理路径（MCTS leaf eval）使用 inference_server 缓存的 pre-encoded `hook_emb`（no_grad 快路径）。

### CounterEncoder

```python
CounterEncoder(max_slots=2000, embed_dim=d_model)
```

输入 `counter_values (B, 1832)`, `counter_sids (B, 1832)`, `active_slot_mask (B, 1832)`。

1. `val_emb = value_proj(value.unsqueeze(-1))`
2. `sid_emb = sid_embed(sid.clamp(0,1999))`
3. `all_emb = val_emb + sid_emb`
4. 按 `active_slot_mask` 排序，取前 `max_active` 个（per-batch）—— `max_active = int(active_slot_mask.sum(1).amax())`
5. Output: `(B, max_active, d)` + mask

**关键**：稀疏化用 `active_slot_mask`（来自 static obs 的 min/max），**不用** `counter_values != 0`。这样 value=0 的真实 counter（e.g. 破盾瞬间、刚耗尽的 AP）仍然被编码，value=0 是有效信息。

### CardEncoder

```python
CardEncoder(n_card_slots=80, n_buckets=4, d_model)
```

1. `tok = bucket_emb(b) + slot_emb(s)` — `(n_buckets, n_slots, d)` 静态 table
2. `count_emb = count_proj(counts.unsqueeze(-1))` — count 的标量投影
3. `tok_emb = tok + count_emb` —— **不乘 counts**（修复 E2，避免双重放大）
4. `mask = counts > 0`; `tok_emb = tok_emb * mask`; mean pool
5. `+ enemy_size_proj(enemy_sizes)` 直接加到 pool 输出

### CrossAttention × 2 layers

```python
CrossAttentionBlock(d_model, n_heads=4, dropout=dropout)
```

双向：

- `c→h`: `counter_emb = LayerNorm(counter_emb + counter_to_hook_attn(counter_emb, hook_emb, hook_emb, key_padding_mask=~hook_mask))`
- FFN on counter_emb + LayerNorm
- `h→c`: `hook_emb = LayerNorm(hook_emb + hook_to_counter_attn(hook_emb, counter_emb, counter_emb, key_padding_mask=~counter_mask))`
- FFN on hook_emb + LayerNorm

两层 stacked。输入输出维度 `(B, N, d)` 保持不变。

### Pool → global_state

```python
counter_pool = (counter_emb * counter_mask).sum(1) / counter_mask.sum(1).clamp(min=1)
hook_pool    = (hook_emb    * hook_mask   ).sum(1) / hook_mask.sum(1)   .clamp(min=1)

# char_skill_pool：gather → mask -1 → masked mean
#   refs:    (B, 2, 6, 10) long, 值 ∈ {-1, 0..n_active-1}
#   gathered = hook_emb[refs.clamp(0)]        (B, 120, d)
#   valid    = (refs >= 0)                   (B, 120)
#   pool     = sum(gathered * valid) / sum(valid).clamp(min=1)
char_skill_pool = masked_mean(gather(hook_emb, char_skill_refs), mask=refs≥0)

card_emb     = card_encoder 输出
meta_emb     = meta_proj(meta)
struct_feat  = struct_head(structural_values)  # (B, d)

global_state = cat([counter_pool, hook_pool, char_skill_pool,
                    card_emb, meta_emb, struct_feat])  # (B, 6d)
```

### Value Head

```python
value_head = nn.Sequential(
    nn.Linear(6*d, 2*d), nn.ReLU(), nn.Dropout(dropout),
    nn.Linear(2*d, 1),
)
value = tanh(value_head(global_state)).squeeze(-1)  # (B,) in [-1, 1]
```

MSE 目标是 `z ∈ {-1, 0, +1}`，tanh 保证 logit 不会跑到过大区间造成饱和。

### Delta Head (Auxiliary — Counter Δ 监督)

```python
delta_head = nn.Sequential(
    nn.Linear(6*d, 2*d), nn.ReLU(), nn.Dropout(dropout),
    nn.Linear(2*d, n_counter_slots),   # 1832
)
delta_pred = delta_head(global_state)   # (B, n_counter_slots)
```

监督任务：给定 `(counter_before, active_hooks, action)`，预测 `counter_after - counter_before`（或直接 `counter_after`）。

存在的原因：C1v6 (batch=64) 诊断显示 cross-attention 层的注意力权重满熵——hook_encoder 活了，但 cross-attn 学不会从数百个 active hook 里选择相关的。counter-Δ 任务**强迫** cross-attn 学习 `hook → counter` 的因果结构（要预测 Δ 必须知道哪些 hook 影响哪些 counter），直接作用于 Q·K 训练信号。

详见 `memory/project_cross_attn_saturation.md`。

### Policy Head (pointer-net)

```python
# 1. state_vec
state_vec = state_proj(global_state)  # (B, d)

# 2. action_emb per legal action
action_emb = gather_or_const(kind, hook_emb[hook_idx], char_slot_emb[char_idx], end_turn_emb)
action_emb = action_emb + dice_combo_proj(payment)  # (B, N_act, d)
action_emb = action_emb_norm(action_emb)

# 3. pointer-net dot product
logits = (state_vec.unsqueeze(1) * action_emb).sum(-1)  # (B, N_act)
```

action_emb 分三路 gather：
- **SKILL / CARD**：`hook_emb[hook_idx]` — 从**post-cross-attention 的 hook_emb** 取（已融合 counter 信息）
- **SWITCH**：`char_slot_emb[char_idx]` — 独立 embedding table（char 槽位不 shuffle，"下一个角色"有稳定语义）
- **END_TURN**：`end_turn_emb` 全局 learned const

全部 `+ dice_combo_proj(payment)` 残差。LayerNorm 收尾。

---

## 损失函数

`az_losses(logits, value, legal_mask, pi_target, z_target, model, l2_coef, entropy_coef)`:

### Policy loss (masked cross-entropy)

```python
masked_logits = logits.masked_fill(~legal_mask, -inf)
log_probs = log_softmax(masked_logits, dim=-1)  # normalized over legal only
log_probs = log_probs.masked_fill(~legal_mask, 0.0)  # kill -inf × 0 = NaN
policy_loss = -(pi_target * log_probs).sum(-1).mean()
```

Contract check：`pi_target` 在非法位必须恰为 0（MCTS visits / sum 天然满足），否则 raise。

### Value loss

```python
value_loss = F.mse_loss(value, z_target)
```

### L2 regularization

```python
for name, p in model.named_parameters():
    if p.requires_grad and p.dim() >= 2:  # skip 1D: biases + LayerNorm weight
        l2 += (p * p).sum()
l2 *= l2_coef
```

**修复 A 后**：只惩罚 weight matrix 和 embedding table，不惩罚 bias / LayerNorm weight（后者初始化为 1，被 decay 会削弱归一化）。

### Entropy regularization

```python
probs = softmax(masked_logits, dim=-1)
entropy = -(probs * log_probs).sum(-1).mean()
# total += -entropy_coef * entropy (encourage high entropy)
```

### Delta auxiliary loss

```python
if config.delta_aux_coef > 0 and "counter_target" in batch:
    row_mask = has_counter_target.unsqueeze(-1) & active_slot_mask  # (B, n_slots)
    diff2 = (delta_pred - counter_target) ** 2
    delta_loss = (diff2 * row_mask).sum() / row_mask.sum().clamp_min(1)
    total += config.delta_aux_coef * delta_loss
```

`has_counter_target=False` 的样本（terminal 转换）被 mask 跳过。当前 `delta_aux_coef=0.1`。

### Total

```python
total = value_loss + policy_loss + l2 - entropy_coef * entropy + delta_aux_coef * delta_loss
```

---

## 训练流

### 进程拓扑

```
┌──────────────┐                   ┌─────────────────┐
│ inference    │←──weight push─────│ main process    │
│ server       │                   │ ├─ trainer loop │
│ (1 proc)     │                   │ ├─ buffer (50k) │
└──────┬───────┘                   │ ├─ arena        │
       │                           │ └─ launcher     │
    eval RPC                       └───┬─────────────┘
       │                               │
┌──────▼─────────────────┐       trajectory
│ 4× self-play worker    │───────────┘
│  MCTS tree + env step  │
│  IS-UCT + λ 混合        │
│  virtual-loss par=4    │
└────────────────────────┘
```

另有独立进程 `tools.remote.eval_service`（固定 socket `/tmp/gicg_eval.sock`），主进程按 `games_per_gauntlet` 发 gauntlet request，service 跑完结果写回 run 的 `gauntlet_results.jsonl`。

### Self-play worker 一局流程

1. **Game start**：
   - worker 构造 env（`sample_teams` 按 `char_pool` 随机采样）
   - 发 `{"kind": "game_start", "static_obs": ...}` 给 server
   - server 算 `encode_static_tensors_with_tokens`：
     - cache pre-encoded `hook_emb, hook_mask, counter_sids, active_slot_mask`（给后续 eval RPC 用）
     - 回包给 worker：`{hook_types, hook_values, hook_mask, counter_sids, active_slot_mask}`（raw tokens，给训练用）
   - worker 存回包为 `game_static`

2. **每个决策点**：
   - 计算 `effective_lambda = compute_annealed_lambda(game_idx)`（0→0.8 over 1500 games）
   - `mcts_search(env, n_rollouts=200, value_mix_lambda=λ, prior_mix_lambda=λ)`
     - snapshot env
     - 每次 rollout：
       - `restore(snap)`
       - `determinize`（SharedFixedPool 采样对手手牌/牌堆）
       - Descend (PUCT 选择 + virtual loss) → 到 leaf → 一次 `inference_client.eval(dyn, refs, payments)` → server batched forward（no_grad）→ 得 `(prior, value_net)`
       - rollout 到终局得 `value_rollout`
       - `value_leaf = λ · value_net + (1-λ) · value_rollout`
       - Backup 树
   - `pi_target = visits / sum(visits)`
   - Temperature sampling → env.step

3. **Game end**：
   - 终局 `winner` → `z_target` (+1/-1/0 从 actor 视角)
   - 每个 step 反填 z（交替翻转视角）
   - worker 发 `game_end`，server 清 cache
   - worker put result 到 main 的 result_queue

### 主进程 trainer loop

每局进 buffer 后：
1. 触发 `train_steps_per_game = 4` 次 `train_step`
2. 每 `sync_weights_every_train_steps = 10` 次 train 后 push weights 到 server
3. 按 `games_per_arena` / `games_per_gauntlet` 触发 arena / gauntlet

### `train_step`

1. 从 buffer 采样 batch（B=256, priority sampling on discovery events）
2. Batch 字段包括 raw `hook_types, hook_values, hook_mask, counter_sids, active_slot_mask`
3. `forward_batch`：
   - `hook_emb = hook_encoder(hook_types, hook_values, hook_mask)` **with grad**
   - 全网 forward (CounterEncoder → CrossAttention × 2 → pool → heads)
4. `az_losses`
5. `total.backward()` + `clip_grad_norm_(max=1.0)` + AdamW step
6. NaN/Inf guard：loss 任一分量非有限 raise

### Inference RPC（worker → server）

```
game_start  (static_obs) → game_static (tokens)
eval        (dyn_obs, refs, payments) → (prior, value_scalar)
game_end    () → ack
```

Server 在空闲点 drain `weight_update_queue` 应用最新 weights。Worker 见到的是 stale weights（10-30 局落后），不影响 AZ 收敛（z / pi_mcts 都是 on-policy to worker 当时 weights）。

---

## 尺寸和参数量

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
| 总参数 | ~1.82M |
| L2 regularize | 1.81M（`dim ≥ 2`）|
| Skip L2 | 11.9k（biases + LayerNorm）|

---

> C1v6 前的六项修复摘要 + 下一步（C1v6 验证）历史叙述 → `docs/5_history/network_design_history.md::c1v6_pre_fixes`（P1-T2 archive）
