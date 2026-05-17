# 训练 — 晋级逻辑（A 方案 + G 方案 + ELO）

> 前置阅读 `docs/training/README.md`. 本文记录每个 stage 的 pass 条件
> （连续 2 次 eval 确认）、partial-pass fallback、ELO-delta 门限和评估参数。

## 晋级：pass_winrate + 连续评估确认（A 方案）

每个子阶段使用 `pass_winrate = 0.55`（预热阶段使用 `0.65`，因为
vs-random 的可达上限更高）。晋级要求**连续两次评估点**均 ≥ 门限，
以避免幸运的单次评估通过。

```
[progression]
pass_winrate = 0.55          # 子阶段
min_iterations = 30
max_iterations = 500
```

Runner 维护最近 2 次评估胜率的双端队列。通过条件：
`len == 2 且两者均 >= pass_winrate`。

统计依据（`n_games = 40`）：
- p=0.55 时 σ ≈ 0.079
- 单次评估在门限 0.55 处的误报率：~26%
- 连续两次均误报：~7%
- min_iterations = 30 + interval = 10 → 至少 3 次评估后才可能通过

## 晋级：max_iter 部分通过（G 方案）

若某子阶段在 `max_iterations = 500` 内未获得连续两次
≥ 0.55 的评估，Runner 检查**部分通过**条件：

- `best_wr ≥ 0.52`（略高于抛硬币）
- 最近 5 次评估胜率的均值 `≥ 0.50`（无明显退化）

若两者均满足，该阶段标记为通过，但检查点有 `.partial.pt` 后缀的副本
（同时也保存正常的 `.pt`，使 prior 链可继续）。课程继续推进到下一阶段。

若两者均不满足，该阶段真正失败：只保存 `.failed.pt`，
`ctx.last_passed_ckpt` 不更新，`train_curriculum` 返回
"failed"——停止整个课程。

## 晋级：ELO delta 门控（review #9，已于 6ffef04 + 14f1ed8 落地）

阶段可通过同时设置
`[progression] pass_elo_delta = X` 和 `[eval] opponent = "pool"`
选用基于 ELO 的门控。Runner 此时使用：

```
[progression]
pass_elo_delta = 30         # 从阶段开始值起所需的 ELO 增长
min_iterations = 30
max_iterations = 500
```

阶段入口时，Runner 将 `ctx.pool.current_elo` 快照为
`stage_start_elo`。每次评估对对手池打一批对局，并应用对称的
国际象棋风格 ELO 更新（K=32）——当前智能体评分和被对战的 pool 成员评分
在每局后均会更新，使 pool 评分随对战自然刷新。
通过条件：**连续两次评估中
`pool.current_elo - stage_start_elo >= pass_elo_delta`**。

注意：
- G 方案的部分通过兜底**不适用**于 ELO 门控阶段——
  若阶段达到 `max_iterations` 未达到 ELO 增长，则直接失败。
- Pool 成员通过对当前智能体 ELO 接近度的 softmax 加权采样
  （温度 200）；智能体最常对战 ELO 差距在 ~200 分以内的对手。
- Pool 由每次成功通过的阶段（包括完整确认和 G 方案部分通过）播种，
  因此课程后期基于 pool 的阶段拥有多样的历史对手可用。

## 评估调节参数

| 参数 | 值 | 原因 |
|------|----|----|
| `interval` | 10 次迭代 | 每 10 次 PPO 更新评估一次 |
| `n_games` | 40 | p=0.55 时 σ ≈ 0.07，方差低 |
| `min_iterations` | 30 | 至少强制 3 次评估周期 |
| `max_iterations` | 500 | 硬上限 |
| `pass_winrate` | 0.55（子阶段）/ 0.65（预热） | A 方案 |

双方交替：智能体在偶数索引对局中执 P0，奇数索引对局中执 P1。
评估 `team_rule` 默认与阶段的训练 `team_rule` 一致（除非显式覆盖）。
