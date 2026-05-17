# C1v6 结果预案矩阵

> 2026-04-17 晚。C1v6 是 F run 后发现 hook gradient bug + 六项网络修复落地后的首个训练。
> 本文预置三种主要结局的行动方案，避免结果到手后再临时拍。

## 2026-04-17 深夜更新：C1v6 batch=64 崩盘 → aux loss 方案

C1v6 第 3 次 run（`202604171904_az_c1v6`, batch=64）跑到 g200 arena 触发 **wr=0.0 (0-40)** 完全崩盘。g100=1.0 健康但 g200 挑战者对 g100 champion 40-0 输。

诊断（`tools/diag_hook_path.py` on ckpt_g00200）：
- hook_encoder 权重正常更新 (ratio=111%)
- Sub-5 CrossAttention entropy **satured 满熵** (4.94/4.94, 5.02/5.02)——cross-attn 注意力几乎完全均匀分布

根因：**hook_encoder 活了，但 cross-attn 学不会从 active hook 集合里选出相关的**。lambda 从 0.05 升到 0.11 时，网络 value/prior 开始介入搜索，但由于 hook 未被有效聚合，noise 被放大毒化 MCTS。

修复方案：**counter-Δ aux loss**（详见 `memory/project_cross_attn_saturation.md`）
- 新 `ActorCritic.delta_head` 预测 `counter_after - counter_before`
- `train.py` 加 `delta_aux_coef=0.1` 的 masked MSE
- `selfplay.py` 收集 per-step counter target（同 acting_player 视角）
- 190/190 单元测试通过

不选 D2 / per-hook ID / lambda 调参：前两者打破反 ID 设计（或不解决根因），lambda 调参只推迟问题。

**下次 run 流程（C1v7 aux loss）**：
1. 启 smoke ~50 局验证管线 OK + cross-attn entropy 开始下降
2. 若 entropy 从满熵降到 < 4.5 → aux loss 生效,启完整 400 局训练
3. 跑 probe_numeric_sensitivity 看 hook_response_ratio
4. 若 entropy 没动 → 升级 D2

## C1v6 配置回顾

- 源：`c1_random_config`（5 角色池，team_size=1，allow_mirror=False）
- 规模：n_games=400，games_per_arena=100（4 次 arena：g100/g200/g300/g400）
- 网络：d_model=128，6 项修复全部落地
- gauntlet：**不自动触发**（games_per_gauntlet=500 > n_games=400）
  - g200 和 g400 手动通过 `tools/send_gauntlet.py` 发请求到 eval_service
- artifacts：`artifacts/202604171646_az_c1v6/`

## 判定维度

| 维度 | 判据来源 |
|---|---|
| **训练稳定性** | metrics.jsonl 的 loss 趋势 + arena wr 序列 |
| **绝对强度** | 手动 gauntlet(g200, g400) vs mcts_200 |
| **hook channel 激活** | `tools/probe_numeric_sensitivity.py` 对 final_champion 的 hook_response_ratio（判据 <0.01 死 / 0.01-0.3 弱 / >0.3 活）|

核心未解假设是第 3 维：hook channel 是否激活。前两维是健康检查。

---

## 预案 1：BEST — hook 显著激活 + 训练稳定

**判据**：
- arena 4 次都换章（wr ≥ 0.55）
- loss 单调收敛（v_loss Q1→Q4 单降，entropy 不 collapse）
- hook_response_ratio > 0.3
- gauntlet g400 vs mcts_200 ≥ 30%（与 F run 可比，场景更硬所以门槛降）

**含义**：
- "反 ID + hook tokenization + 领域随机化" 的核心架构假设**首次被公平验证通过**
- 六项修复正确且足够
- D2 不必做

**下一步**：
1. **commit 六项修复**（用户确认后）
2. 启 **C2 = L1+L2 卡池**（800-1000 局，验证 card 通道的泛化）
3. 若 C2 也成功 → **C3 = team_size ∈ {1,2}**（验证 team_size 泛化）
4. 若 C3 也成功 → 进入 scaling（更大 d_model / 更多 hook）

**时间线**：C2 约 12h，C3 约 24h。

---

## 预案 2：MID — 管线健康但 hook 响应弱

**判据**：
- arena 至少 2 次换章（训练没崩）
- loss 稳定
- **hook_response_ratio 在 0.01 到 0.3 之间**
  - value 有响应但 top1 很少变
  - 或 top1 有时变但 |Δv| 远小于 counter baseline
- gauntlet g400 vs mcts_200 在 15-30%

**含义**：
- hook channel 没死（Δv > 0 就证明梯度流是通的）
- 但 policy 对 hook 的利用不充分
- 最可能原因：policy state_vec 虽然加了 hook_pool（D1），但 pointer-net 内部仍倾向于主要靠 counter。mean pool 信号被 global state 稀释

**下一步**：

### 2a. 先再跑一次更长 run
- 400 局可能不够让 hook 影响力充分显现
- 启 **C1v6-extended = 1000 局，相同配置**，看 ratio 是否随训练推进上升

### 2b. 若 C1v6-extended 仍 weak 响应 → 升级 D2
- 实施 `project_d2_state_hook_attention.md` 描述的 state→hook attention pool
- 新增 MultiheadAttention 层（~64k 参数）
- 重训一轮（C1v7）

### 2c. 若 D2 也 weak → 诊断 HookEncoder 表达力
- HookEncoder 可能表达力不足（d=128 Transformer 2 层处理平均 100-200 token 序列）
- 测试：HookEncoder 在 C1v6 ckpt 下能否学出 "相同 hook 给同 embedding"（收敛）→ 若不能，encoder capacity 问题
- 候选修复：HookEncoder n_layers 2→3 或 d_model 128→256（代价：eval 耗时 ~2x）

---

## 预案 3：WORST — hook 完全不响应 + 训练异常

**判据**：
- **hook_response_ratio < 0.01**（和 F 一样死）
- 或 loss 曲线崩坏：v_loss 不降 / p_loss 反升 / entropy collapse (< 0.5)
- 或 arena 0 次换章

**含义**：
- 六项修复**不够**或**有回归**
- hook_encoder 梯度虽然通了但仍然没学到有用信号
- 可能是：
  - 架构问题：HookEncoder + CrossAttention 的梯度信号太弱（消失梯度）
  - 训练问题：lambda 退火太慢，网络永远没真正介入决策
  - 损失问题：policy CE 对 hook channel 的监督不够（因为 policy 主要从 counter 预测）

**立即诊断**：

### 3a. 跑 diag_hook_path 确认梯度 + 权重状态
- 新 ckpt 的 hook_encoder 权重 L2 norm 是否正常（不接近 0）
- 如果权重正常但输出仍无变化 → Transformer 本身可能有问题（LayerNorm 塌缩 etc）

### 3b. 查 attention entropy
- CrossAttention 的 counter→hook 方向 attention 是否是均匀分布（entropy 满）
- 若是 → cross-attention 没学到怎么用 hook → 架构问题

### 3c. 根据 3a/3b 决定下一步

| 3a 结果 | 3b 结果 | 结论 / 下一步 |
|---|---|---|
| 权重 ≈ 0 | - | 修复回归，回到 hook gradient bug，查 train_step 是否真的用了 forward_batch |
| 权重正常 | 均匀 | cross-attention 没学 → 换 D2（state-aware attention）或加 aux loss 监督 hook |
| 权重正常 | 有结构 | hook_pool 的 mean 太稀释 → D2 或换 attention-based pool |

**最坏情况兜底**：
- 如果所有架构修改都不激活 hook channel，需要承认"数值 token tokenization + Transformer"这个设计方向可能不 work
- 回到 design doc（decisions.md D8 / network_design.md）重审基于特征的 embedding 方案
- 可能要用 hand-crafted feature vector 替代 token sequence

---

## 手动 gauntlet 触发点

C1v6 无自动 gauntlet。需在以下节点手动发：

| 节点 | 触发条件 | 命令 |
|---|---|---|
| g200 | `ckpt_g00200.pt` 生成（checkpoint_every_n_games=200） | `python -m tools.send_gauntlet artifacts/202604171646_az_c1v6/ckpt_g00200.pt --game-marker 200` |
| g400 | `=== DONE ===` 出现（final_champion.pt） | `python -m tools.send_gauntlet artifacts/202604171646_az_c1v6/final_champion.pt --game-marker 400` |

结果写入 `artifacts/202604171646_az_c1v6/gauntlet_results.jsonl`。

---

## 扰动诊断触发点

- g400 gauntlet 完成后立即跑：
  ```
  python -m tools.probe_numeric_sensitivity \\
      artifacts/202604171646_az_c1v6/final_champion.pt \\
      --config c1_random
  ```
- 输出 `hook_response_ratio` 和 verdict
- 根据 verdict 进入上面 3 个预案之一

---

## 不该立即做的事（避免决策漂移）

- ❌ C1v6 过程中改网络架构：任何改动等到扰动结果出来
- ❌ 中途 kill C1v6：除非 crash 或 loss 发散（v_loss > 1 持续 > 100 局）
- ❌ 启平行 run：等 C1v6 完成拿到结论再决策下一 run
- ❌ "C1v6 太慢" 就切回 F 或早期 ckpt：那些 ckpt 作废

---

## Followup 列表（C1v6 之后独立做，不受预案影响）

| 优先级 | 项 | 来源 |
|---|---|---|
| 低 | MPS bench d_model=128 | 性能优化 |
| 低 | 任务 #152 dynamic hook 架构（方案 B）| mirror match bug |
| 中 | inference_server 侧 forward-time profile | bottleneck 诊断 |
| 中 | CardEncoder count pooling（E2 的进阶）| 扩卡池前 |
| 中 | `n_counter_slots` 对 team_size≥2 是否够 | 未来扩 team_size |
