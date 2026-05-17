# r009 设计:F1-D2 Behavioral Cloning warm-start

> **⚠️ SUPERSEDED (2026-04-24).** 本 r009 计划写完后,paradigm pivot 决策走了
> curriculum 路线 (PPO Stage 0-3),没有按本 plan 跑 r009 production run。
> Stage 3 closure 后 (2026-04-26),AZ 路线的新 r009 候选见
> [`../../5_history/az_plans/r009_az_warmstart.md`](../../5_history/az_plans/r009_az_warmstart.md)(已归档)
> (BC warm-start AZ,与本 plan 思路一致但目标网络是 AZ ActorCritic 而非 PPO MLP)。
> 本 doc 保留作历史参考。

**日期:** 2026-04-24
**paradigm:** 混合(P0-1 of [adr-0008 paradigm pivot](../../2_decisions/adr-0008-rl_paradigm_pivot.md))
**前置:** r008 CFR 失败 + greedy F1-D2 dice_greedy = 0.90 vs mcts_200 实证

## 目标

用 F1-D2 dice_greedy 作 teacher,BC 训一个网络,达成:

1. **policy head match F1-D2 argmax ≥ 80%**(on held-out states)
2. **gauntlet vs mcts_200 ≥ 0.80**(下限接近 F1-D2 teacher 的 0.90)
3. **value head 粗略拟合终局**(MSE(v_pred, z) 下降,绝对值不苛刻)

r009 **不追求超过 F1-D2** — 那是 r010 的事。r009 只验证:
- 网络容量能装下 F1-D2 的启发式
- 现有 obs 足以重建 F1-D2 决策(若不够,需先修 obs/结构,不是继续训)
- BC 数据 pipeline + loss 形式 OK

**若 r009 match rate < 60%**,不要进 r010 — 先修网络/obs,因为 fine-tune 在破 teacher 之下的基础上无意义。

## 设计关键点

### 1. Teacher 选 F1-D2,不选 F5-D2 或其他

s007 实证 F1 > F2 > F3 > F4 > F5 每步 0.90。F1-D2 是最强 greedy。F5-D2 用的
shaped features 在此场景是噪声。但 F5-D2 更慢(需要 RewardEvents 查询),
per game ~88s vs F1-D2 的 ~64s。

**选 F1-D2 dice_greedy + D=2**(minimax 2-ply)。

风险:F1-D2 对 mcts_200 有 10% 失败域(典型是长程 combo 规划),网络可能
也学不到这些 — BC 下限本身有 ceiling。r010 fine-tune 的使命就是突破这个
ceiling。

### 2. 数据生成:自对弈 + exploration + opponent variety

**纯 F1-D2 vs F1-D2** 在同一固定 team 下轨迹过度确定 — random tiebreak 带的
多样性有限,网络学到的会 overfit 到少数固定棋局模式。

**三层 exploration 混合:**

a. **Soft teacher target(软标签):** 不用 one-hot(argmax),用 F1-D2 的原始
   score 做 softmax。网络学到的是"相对优劣",不只是"哪个最好"。
   ```
   scores = [F1-D2 score for each legal action]
   pi_teacher = softmax(scores / T),T = 0.5
   ```
   T=0.5 是 one-hot 和 uniform 的中间。实际 sample 动作仍按 argmax(训练时
   target 是 soft,行为仍是 greedy,轨迹分布保真)。

b. **Opponent variety:** 50% 场次 F1-D2 vs F1-D2,30% F1-D2 vs F1-D1
   (弱对手,产生不同棋局),20% F1-D2 vs greedy mix 的 Boltzmann 采样
   (T=0.3,不 pure argmax)。

c. **起始种子多样化:** 每局换 seed,dice/card draw 分布覆盖广。

**只记录 F1-D2 一侧(teacher 侧)的决策**作训练样本 — 对手侧(F1-D1)质量低,
不要当 label 源。`swap_sides=true` 随机切换 teacher 到 P0 或 P1,两侧
obs shape 都覆盖。

### 3. 数据量和格式

**目标:50k 个"teacher 决策"样本**,不是 50k 局。

估算:
- 每局 ~300 步总决策,teacher 决策 ~150/局
- 50k decisions ≈ 330 局
- 保守放大 10×,跑 3000-5000 局,获 450k-750k teacher decisions
- 每局 F1-D2 wall ~10s,3000 局 × 10s / 4 workers = 125 min ≈ **2h wall time**

**比我原估(50k 局)少 10×**。BC 不需要海量数据,需要覆盖广。

**格式:** 每局一个 npz,字段与现有 `training/az/buffer.py::ReplayBuffer` 的
step dict 同构,加一个 `teacher_scores: (max_actions,) float32`(原始 F1-D2 分数,
用于复原 soft target + 未来换 T 调试):

```
game_static.npz: hook_types, hook_values, hook_mask, counter_sids,
                 active_slot_mask, char_skill_refs
per_step.jsonl(or npz with list): counter_values, meta, card_buckets,
                 enemy_sizes, action_refs, action_payments, legal_mask,
                 teacher_scores, teacher_argmax, acting_player
terminal: z_target(±1/0), winner
```

存 `artifacts/{ts}_r009_bc_data/` 下,子目录 `games/NNNN/`。

### 4. 网络:复用现有 Agent,先不动 d_model

`training/az/network/agent.py::Agent` 当前 d_model=128。C1v7 架构(struct_readout)
保留。

**先试 d_model=128 baseline**。若 match rate 低但训练曲线还在下降,加大到 256。
不把网络扩展放在 r009 起点(控制变量)。

### 5. Loss

```
L_policy = CE(log_softmax(pi_pred), pi_teacher_soft)      # soft target KL
L_value  = MSE(v_pred, z_terminal)                          # value head
L_total  = L_policy + 0.5 * L_value
```

**没有 counter delta aux loss**(原 AZ 用的,BC 阶段不涉及)。

**Legal mask 处理:** pi_pred 和 pi_teacher 都要 mask 非法 action slots
(pi_teacher 的非法 slot 设 -inf 然后 softmax,pi_pred 用 legal_mask)。

### 6. 训练超参

- Optimizer: Adam
- LR: 3e-4(标准 BC / SL 学习率)
- Batch size: 256(和 AZ 一致)
- 总 steps: **先训 10k steps**,每 1k step 评估一次 match rate。观察到平台(连续 2-3 个检查点
  不升)即停。预估 20k-50k steps 足够。
- LR schedule: cosine decay 到 3e-5 over total steps
- Dropout: 0.1(防 teacher 标签噪声过拟合)
- Grad clip: max_norm=1.0

### 7. 评估协议

每 1k step:
- **Held-out match rate**: 用 500 局验证集(从不参与训练,数据生成阶段预留)
  的每个 teacher decision,算 network argmax vs teacher argmax 一致率
- **Value MSE** on held-out
- **Quick gauntlet**(每 2k step 一次,10 局 vs random 快速健康检查)

训练结束后,full gauntlet:
- vs F1-D2(最严苛:和 teacher 对比,期望 ~50% = teacher 级别)
- vs F1-D1(弱 teacher,期望 ≥ 70%)
- vs mcts_200(真实基线,**目标 ≥ 0.80**)
- vs random(sanity,期望 ≥ 0.95)

### 8. Go / No-go 判据

| 指标 | 结果 | 动作 |
|---|---|---|
| match rate ≥ 80% & vs mcts_200 ≥ 0.80 | ✓ 进 r010 fine-tune | |
| match rate 60-80% | 部分 | 加大 d_model 到 256 重训一版 r009.5 |
| match rate < 60% | 失败 | 停,诊断:(a) obs 缺字段(HP 不在 obs?);(b) 网络表达能力不足;(c) 数据量不够 |
| match rate ≥ 80% 但 vs mcts_200 < 0.60 | 意外 | 说明 match rate 不等价于实战强度,审 teacher score 与真实 value 的关联 |

## 实现清单

| 项 | 文件 | 行数估 | 依赖 |
|---|---|---|---|
| 1. BC 数据生成器 | `tools/gen_bc_trajectories.py` | 150-200 | framework.matchup.loaders、greedy_player |
| 2. BC 训练循环 | `training/az/bc_train.py` | 200-300 | 现有 Agent、ReplayBuffer 的加载格式 |
| 3. 预设 config | `configs/r009_bc_warmstart.toml` | 30 | |
| 4. Match rate 评估器 | `tools/eval_bc_match.py` | 80-100 | Agent + F1-D2 并跑 |
| 5. Launcher | `tools/run_r009.sh` or run_r009.py | 50 | 封装全流程 |
| 6. Registry 写入 | 调 `tools.register_run` | — | — |

**总工作量:** ~2-3 天实现 + 1-2 天 tune。

## 与 r010 衔接

r010 = P0-2 + P0-3 组合:
- 从 r009 的 ckpt 初始化(不再 random init)
- AZ 训练,但 **MCTS leaf eval 用 truncated greedy F1-D1 rollout** 而非 net-value
- reward 加 HP delta shaping,λ 从 0.3 退到 0.05
- 短训(400g)验证能否突破 r009 的 F1-D2 ceiling 达 vs mcts_200 ≥ 0.95
- 若退回 teacher 强度(regress),说明 fine-tune 动 BC 学的太狠,调 KL penalty

## 与前次失败的对比

| 方面 | r001-r008 | r009 |
|---|---|---|
| 起点 | random init | F1-D2 BC |
| 下限(已知) | 0(r008 iter 20 最强是巧合) | F1-D2 = 0.90(BC 成功后) |
| 信号密度 | 终局 ±1 | teacher 每步 soft label |
| Search | MCTS + random rollout | 无 search(纯 BC 预训) |
| Self-play 污染 | 长期,正反馈 | 离线 BC,无反馈 |

r009 不是 RL,是 SL/BC。r010 才是 RL,但基于已有下限,不会 regress 到 0。

## 时间线

- Day 0-1: 实现数据生成器 + 跑 3000-5000 局 F1-D2 self-play(~2h wall)
- Day 1-2: 实现 BC 训练 loop + 跑 10k-50k steps(~4h wall)
- Day 2: Full gauntlet + 诊断 + 决定 r010 启动条件
