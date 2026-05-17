# 网络架构 — Dropout 与 train/eval 模式

> 前置阅读：`docs/network/README.md`（架构概览）和 `docs/network/implementation.md`
> （当前代码模块）。本文聚焦 dropout 引入的动机、实现细节和 train/eval mode 策略。

## 6. Dropout 与 train/eval 模式策略

Dropout 被添加到以下位置：
- `CrossAttentionBlock` 的两个 MultiheadAttention 模块（`dropout=p`）
- 注意力输出残差路径（`attn_drop_c2h/h2c`）
- 两个 FFN（在 Linear/ReLU/Linear 之间，以及第二个 Linear 之后）
- `state_proj` 和 `value_head`（各自的 ReLU 之后）。`state_proj`
  替代了旧的基于位置的 `policy_head`；指针网络点积本身没有 Linear 层可以 drop。

**默认 `dropout = 0.1`**，可通过阶段 TOML 中的 `[model] dropout = X` 按阶段配置。
设置 `dropout = 0` 可禁用（与原始无 dropout 架构行为一致，无需其他代码修改）。

### 为何在此代码库中引入 dropout

在引入 dropout 之前，phase0_v3 训练呈现出明显的异常：cross-attention 第 0 层
具有结构化的按组注意力，但第 1 层在所有 counter 组和 hook 索引上几乎是均匀分布。
这是标准 Transformer 的"注意力收敛"模式——残差 + LayerNorm 会使各层的表示趋于同质化，
导致第 1 层没有足够的区分动力。

引入 dropout 后，模型被迫在第 0 层的输出中保持冗余
（因为训练时第 1 层看到的是加了噪声的版本），
从而给第 1 层更多的激励去专注于能在 dropout 噪声中存活下来的模式。

### Train 与 eval 模式

- **Rollout**（collect_episode）：**train 模式**，dropout 激活。
  存储的 `old_log_prob` 带有 dropout 噪声。
- **PPO 更新**：**train 模式**，dropout 激活。关键在于与 rollout 保持相同的分布——
  否则重要性比率 `π_new / π_old` 在任何梯度步骤之前的第 0 次迭代就会产生偏差。
- **评估**（`evaluate`）：**eval 模式**，dropout 关闭。评估衡量的是确定性策略。
  `train_stage` 在调用 `evaluate` 前执行 `agent.net.eval()`，
  紧接着再执行 `agent.net.train()`。

这是保守选择。有些实现使用 eval 模式 rollout（dropout 关闭，确定性数据采集）
+ train 模式更新（dropout 开启），但这会在重要性比率中引入偏差，需要仔细调参。

### 向后兼容性说明

在 `nn.Sequential` 中插入 `nn.Dropout` 会导致 state_dict 的键索引偏移。
旧检查点（dropout 引入前的时代）**无法加载**到新模型中。
这是引入 dropout 时接受的一次破坏性变更——此前保存的 phase0_v3 ckpt（共 60 次迭代）
保留价值不高。

如果未来的架构变更也破坏兼容性，推荐做法：
- 使用命名子模块代替 `nn.Sequential`（`self.fc1 = ...; self.fc2 = ...`）
- 或对 state_dict 进行版本管理，并在加载时添加迁移步骤
