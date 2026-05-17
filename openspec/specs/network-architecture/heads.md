---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: network-architecture
subtopic: heads
---

# Heads — Value / Delta / Policy

> 本 subtopic 锚定 GICG 网络的三个 head:value head(scalar,tanh
> bounded)、delta head(auxiliary counter-Δ supervision)、policy head
> (pointer-net,反 ID)。所有 head 消费 `global_state ∈ ℝ^{B × 6d}`
> 由 [`./encoders.md`](./encoders.md) Pool 层生成。
>
> Head 数量目前为 3(value + delta + policy-tactical)。未来 head
> (deckbuild D11 / dice-aware action features D7)需以 OpenSpec change
> 形式扩展,不在本 spec 范围。

## 1. Scope

本 subtopic 覆盖:

- Value head(MLP `6d → 2d → 1`,tanh)
- Delta head(MLP `6d → 2d → n_counter_slots`,auxiliary)
- Policy head(pointer-net + 3-way gather + dice_combo residual)
- 共享主干 + 多头分派的设计契约(`forward` 接口)

## 2. Value head

### 2.1 SHALL invariants

1. Value head SHALL output a single scalar `v` per batch entry,bounded
   to `[-1, 1]` via `tanh`。SHALL NOT emit unbounded logit(防爆 +
   与 MSE 目标 `z ∈ {-1, 0, +1}` 对齐)。
2. Value head SHALL be a 2-layer MLP `6·d → 2·d → 1` with ReLU +
   Dropout in between。
3. Value head SHALL be shared across all paradigms / stages — 在所有
   stage(当前 tactical;未来 deckbuild)由相同样本训练,通过
   `global_state` 上预测 final game outcome,作为跨 stage 知识转移
   通道。

### 2.2 结构

```python
value_head = nn.Sequential(
    nn.Linear(6 * d, 2 * d), nn.ReLU(), nn.Dropout(dropout),
    nn.Linear(2 * d, 1),
)
value = tanh(value_head(global_state)).squeeze(-1)  # (B,) in [-1, 1]
```

MSE 目标是 `z ∈ {-1, 0, +1}`,`tanh` 保证 logit 不会跑到过大区间造成
饱和。

## 3. Delta head(auxiliary)

### 3.1 SHALL invariants

1. Delta head SHALL output `(B, n_counter_slots)` predicting
   `counter_after - counter_before`(or `counter_after` directly)
   conditioned on `(counter_before, active_hooks, action)`。
2. Delta head SHALL be optional — 受 `delta_aux_coef` 控制;
   `delta_aux_coef = 0` 时 delta head 仍 forward(避免架构变更)但
   不计 loss。详 [`./loss.md`](./loss.md)。
3. Delta loss SHALL be masked by `has_counter_target` × `active_slot_mask`
   (terminal 转换或非真 slot 跳过)。

### 3.2 结构

```python
delta_head = nn.Sequential(
    nn.Linear(6 * d, 2 * d), nn.ReLU(), nn.Dropout(dropout),
    nn.Linear(2 * d, n_counter_slots),   # 1832
)
delta_pred = delta_head(global_state)   # (B, n_counter_slots)
```

### 3.3 设计契约

Delta head 存在的原因:C1v6 batch=64 诊断显示 cross-attention 注意力
权重满熵 — hook_encoder 活了,但 cross-attn 学不会从数百个 active hook
里选择相关的。counter-Δ 任务**强迫** cross-attn 学习 `hook → counter`
的因果结构(要预测 Δ 必须知道哪些 hook 影响哪些 counter),直接作用于
Q·K 训练信号。

C1v7 加入 struct_readout 后,delta head 不再是主要训练信号路径,但保
留作为 cross-attn 的辅助监督。当前 `delta_aux_coef = 0.1`。

历史:`docs/5_history/network_design_history.md::cross_attn_saturation`。

## 4. Policy head(pointer-net,tactical)

### 4.1 SHALL invariants

1. Policy head SHALL be pointer-net — logits computed as dot product
   `logit[a] = ⟨state_vec, action_emb[a]⟩`,SHALL NOT be a softmax
   over a fixed action-ID embedding table(违反反 ID 原则)。
2. `state_vec` SHALL be `state_proj(global_state) ∈ ℝ^{B × d}`,
   `state_proj` 内部可为 MLP(当前 `6d → 2d → d`)。
3. `action_emb` SHALL be gathered per legal action by `kind`(3 路):
   - **SKILL / CARD**:`hook_emb[hook_idx]` — 从 **post-cross-attention**
     的 `hook_emb` 取(已融合 counter 信息)
   - **SWITCH**:`char_slot_emb[char_idx]` — 独立 embedding table
     (char 槽位不 shuffle,"下一个角色" 有稳定语义)
   - **END_TURN**:`end_turn_emb` — 全局 learned const
4. `action_emb` SHALL add `dice_combo_proj(payment)` 残差,end with
   `action_emb_norm`(LayerNorm)。
5. Policy head input SHALL include `legal_mask`;mask SHALL be applied
   in loss(详 [`./loss.md`](./loss.md)),SHALL NOT silently zero
   logits before softmax。

### 4.2 结构

```python
# 1. state_vec
state_vec = state_proj(global_state)  # (B, d)

# 2. action_emb per legal action
action_emb = gather_or_const(kind, hook_emb[hook_idx],
                             char_slot_emb[char_idx], end_turn_emb)
action_emb = action_emb + dice_combo_proj(payment)  # (B, N_act, d)
action_emb = action_emb_norm(action_emb)

# 3. pointer-net dot product
logits = (state_vec.unsqueeze(1) * action_emb).sum(-1)  # (B, N_act)
```

### 4.3 反 ID 与对齐契约

- Policy head 不持有 per-card-ID 或 per-skill-ID embedding table —
  SKILL/CARD 的 action_emb 由 post-xattn `hook_emb` gather,与
  `char_skill_refs` gather 用的**同一个** canonical hook embedding。
  动作选择和观测侧表示对齐,网络对对方技能有**显式**可见性,不靠
  legal_actions 相关性学 skill_id → owner 映射。
- SWITCH 的 `char_slot_emb` 是 per-char-slot 学习 table(不是
  per-char-ID),slot 在 game 内顺序稳定,语义为"下一个角色 / 第
  N 槽"。
- END_TURN 是 learned const,无 ID 概念。
- dice_combo_proj 在 MVP(AP 万能骰)阶段退化为约零残差(payment 多为
  全零)— 真实骰子系统上线时才显著影响 logit,不影响当前架构。

## 5. 共享主干 + 多头分派

### 5.1 SHALL invariants

1. `ActorCritic.forward` SHALL be plug-extensible — 新 head(deckbuild
   D11 / dice-aware D7)接入 SHALL only need few-line registration,
   SHALL NOT require trunk refactor。
2. Policy head SHALL be selected by `phase`(当前 MVP `phase="tactical"`
   恒成立)— `forward(phase=...)` 分派至对应 head。

### 5.2 已知 NOT SHIPPED 头

历史 design 提出但未 shipped 的 head:

- **`policy_deckbuild`**(D11) — pick card from pool / done;预期复
  用 trunk + value head(MVP placeholder)
- **`card_feature_proj`** — per-card feature 嵌入(D8),CardEncoder 残
  差路径,需要 1000+ 卡池泛化时启用
- **`CharEncoder`** — 替代隐式"角色即 counter 组" 模型;当前 C1v7
  struct_readout 已覆盖 HP/Energy/Alive/Active,需 100-300 角色池时
  重评估

加入任一 head SHALL 走 OpenSpec change,本 spec 同步扩展。

## 6. Cross-reference

- **Global state source**:[`./encoders.md`](./encoders.md) §6 Pool
- **Loss formulation**:[`./loss.md`](./loss.md) — policy CE masked /
  value MSE / delta aux masked
- **History**:
  `docs/5_history/network_design_history.md::charencoder_not_shipped` /
  `cross_attn_saturation` / `policy_head_pointer_net_evolution`
