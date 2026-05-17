---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: network-architecture
subtopic: loss
---

# Loss — Policy / Value / L2 / Entropy / Delta / Total

> 本 subtopic 锚定 GICG 主网络的训练 loss 契约 — 5 个分量 + 加总。
> 入口为 AZ paradigm-local `AZLoss`(详 `training/paradigms/az/loss.py`,
> 接受 `logits, value, legal_mask, pi_target, z_target, model, l2_coef,
> entropy_coef`)。所有 NaN/Inf 由 train loop guard 检测,任一分量非有
> 限 SHALL raise。
>
> Note (`core-network-generic-promotion` archive 2026-05-17):历史曾把
> AZ loss 放在 `training/core/network/legacy/loss.py::az_losses` 作
> paradigm-agnostic helper,但实际只有 AZ 调用。本 capability 重设计后,
> loss 函数 SHALL 位于 paradigm 内部(`paradigms/az/loss.py::AZLoss`)。
> 历史名 `az_losses` 不在新 code path 引用。
>
> 上下文:value/policy/delta head 输出来自 [`./heads.md`](./heads.md);
> head 消费 [`./encoders.md`](./encoders.md) Pool 层的 `global_state`。

## 1. Scope

本 subtopic 覆盖:

- Policy masked cross-entropy(legal mask 必正确)
- Value MSE
- L2 regularization(skip `dim < 2` 防 LayerNorm scale 塌缩)
- Entropy regularization(via `entropy_coef`)
- Delta auxiliary loss(via `delta_aux_coef`,masked by has_target)
- Total combination
- NaN/Inf guards

## 2. Policy loss(masked cross-entropy)

### 2.1 SHALL invariants

1. Policy loss SHALL be cross-entropy of MCTS visit distribution
   `pi_target` against masked log-softmax of logits over **legal**
   actions only。
2. `pi_target` SHALL be zero on non-legal positions — caller(MCTS
   visits / sum)naturally satisfies this;loss function SHALL
   contract-check(raise on violation),SHALL NOT silently normalize。
3. Masked log-softmax SHALL fill `-inf` on non-legal then `log_softmax`,
   then SHALL replace `-inf × 0 = NaN` results with `0.0` before
   multiplication(防 NaN 传播)。

### 2.2 实现

```python
masked_logits = logits.masked_fill(~legal_mask, -inf)
log_probs = log_softmax(masked_logits, dim=-1)  # normalized over legal only
log_probs = log_probs.masked_fill(~legal_mask, 0.0)  # kill -inf × 0 = NaN
policy_loss = -(pi_target * log_probs).sum(-1).mean()
```

Contract check:`pi_target` 在非法位必须恰为 0(MCTS visits / sum 天然
满足),否则 raise。

## 3. Value loss

### 3.1 SHALL invariants

1. Value loss SHALL be `F.mse_loss(value, z_target)`。
2. `z_target` SHALL be in `{-1, 0, +1}`(from-actor 视角 ±1 / draw 0);
   `value` 已经 tanh-bounded(详 [`./heads.md`](./heads.md))。
3. Value loss SHALL NOT carry a separate coefficient(标准 AZ 用 1.0)—
   `value_loss` 直接进 total。

### 3.2 实现

```python
value_loss = F.mse_loss(value, z_target)
```

## 4. L2 regularization

### 4.1 SHALL invariants

1. L2 SHALL iterate `model.named_parameters()` and **skip params with
   `p.dim() < 2`** — 即 skip biases + LayerNorm weight(后者初始化
   为 1,被 decay 会削弱归一化)。这是修复 A 的 invariant。
2. L2 coefficient is `l2_coef`(当前 cfg 默认 `1e-4`);SHALL be applied
   as `(p * p).sum()` 累加后乘 `l2_coef`(non-decoupled,直接进
   total loss)。
3. L2 SHALL be deterministic — 同一 model state 同一 cfg 给出同一
   `l2` 值;SHALL NOT include随机 sampled subset。

### 4.2 实现

```python
for name, p in model.named_parameters():
    if p.requires_grad and p.dim() >= 2:  # skip 1D: biases + LayerNorm weight
        l2 += (p * p).sum()
l2 *= l2_coef
```

**修复 A 后**:只惩罚 weight matrix 和 embedding table,不惩罚 bias /
LayerNorm weight。当前 11.9 k params 跳过 L2,1.81 M params 受 L2。

## 5. Entropy regularization

### 5.1 SHALL invariants

1. Entropy SHALL be computed on the **legal-masked** softmax probability
   distribution(与 policy loss 用同一 `masked_logits` / `log_probs`)。
2. Total loss SHALL add `-entropy_coef × entropy`(负号意味着鼓励
   high entropy);`entropy_coef ≥ 0`。
3. AZ 默认 `entropy_coef = 0`(原始 AZ 探索来自 root Dirichlet 噪声,
   不靠策略熵)— 留 nonzero 作为 paradigm-specific hook。

### 5.2 实现

```python
probs = softmax(masked_logits, dim=-1)
entropy = -(probs * log_probs).sum(-1).mean()
# total += -entropy_coef * entropy  (encourage high entropy when coef > 0)
```

## 6. Delta auxiliary loss

### 6.1 SHALL invariants

1. Delta loss SHALL be applied **only when** `config.delta_aux_coef > 0`
   AND `counter_target` is present in the batch。Absent target 样本
   (e.g. terminal 转换)SHALL be masked,SHALL NOT contribute to
   gradient。
2. Per-element mask SHALL combine `has_counter_target` × `active_slot_mask`
   — 双重保护,确保只在 (a) 有 target 的样本且 (b) 真 counter slot 上
   计 loss。
3. Delta loss SHALL be `mean over masked elements`,denom clamped to
   `min=1`(防 zero-mask div0)。
4. Total loss SHALL add `delta_aux_coef × delta_loss`;当前默认
   `delta_aux_coef = 0.1`。

### 6.2 实现

```python
if config.delta_aux_coef > 0 and "counter_target" in batch:
    row_mask = has_counter_target.unsqueeze(-1) & active_slot_mask  # (B, n_slots)
    diff2 = (delta_pred - counter_target) ** 2
    delta_loss = (diff2 * row_mask).sum() / row_mask.sum().clamp_min(1)
    total += config.delta_aux_coef * delta_loss
```

`has_counter_target = False` 的样本(terminal 转换)被 mask 跳过。

## 7. Total loss

### 7.1 SHALL invariants

1. Total loss SHALL be the sum of 5 terms(value + policy + L2 + entropy
   adjustment + delta aux):

   ```
   total = value_loss + policy_loss + l2
         - entropy_coef * entropy
         + delta_aux_coef * delta_loss
   ```

2. Each term's coefficient(`l2_coef`、`entropy_coef`、`delta_aux_coef`)
   SHALL be read from cfg,SHALL NOT be hardcoded in loss function。
   `value_loss` 与 `policy_loss` 不带系数(系数恒 1.0)。

3. Train loop SHALL guard:任一 term(value / policy / l2 / entropy /
   delta)非有限(NaN / Inf)SHALL raise immediately,SHALL NOT
   silently mask or zero out。

### 7.2 实现

```python
total = value_loss + policy_loss + l2 - entropy_coef * entropy + delta_aux_coef * delta_loss
```

## 8. NaN/Inf guard

### 8.1 SHALL invariants

1. After `total.backward()`,gradient clip SHALL apply via
   `clip_grad_norm_(max=1.0)`。AdamW step follows。
2. Before / during loss compute,SHALL raise on any non-finite term。
   Stage:loss function return + per-component sub-check。
3. Replay buffer `counter_target` SHALL itself never carry NaN(MCTS
   side enforces);若 buffer 端污染 raise 在 forward。

## 9. Cross-reference

- **Heads**:[`./heads.md`](./heads.md) — `logits` / `value` /
  `delta_pred` 由 head 输出
- **Encoders**:[`./encoders.md`](./encoders.md) §8 — 总参数 1.82 M /
  L2 skip 11.9 k(biases + LN)
- **Training pipeline**:[`./training-pipeline.md`](./training-pipeline.md) —
  `train_step` 在何处调用 paradigm `AZLoss`、grad clip、weight push
- **Paradigm divergence**:各 paradigm 可调 `entropy_coef` /
  `delta_aux_coef`(via cfg)而无需偏离架构;具体 paradigm dossier 治理
