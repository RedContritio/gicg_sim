# 训练 — 超参数与产物布局

> 前置阅读 `docs/training/README.md`. 本文记录网络/PPO/训练 cadence 超参，
> run 产物路径约定，以及 ELO 评级系统的长期方向。

## 网络超参数

```
d_model            = 64
n_cross_layers     = 2
n_heads            = 4
dropout            = 0.1   (可通过 [model] 部分按阶段配置)
max_actions        = 64
n_counter_slots    = 1832
n_hooks            = 900
max_tokens_per_hook = 120
```

总参数量：约 510K。

**Dropout 策略**：
- 在 PPO rollout 和 ppo_update 期间均激活（使 old/new log_prob 分布匹配——避免重要性比漂移）
- 在 `evaluate` 期间禁用（确定性策略测量）；
  `train_stage` 在每次评估前后切换 train/eval 模式

## PPO 超参数

```
clip          = 0.2
gae_lambda    = 0.95
gamma         = 0.99
n_epochs      = 3
batch_size    = 128
entropy_coef  = 0.03
lr            = 3e-4
```

## 训练 Cadence

```
episodes_per_iteration = 16
max_episode_steps      = 200
```

每次迭代：
1. 按 `training.opponent` 模式收集 16 个 episode
2. 填充 hook 嵌入，计算 GAE
3. PPO 更新（3 个 epoch，batch 128）
4. 每 10 次迭代：评估（40 局），检查晋级条件

## Session 产物布局

```
artifacts/
├── <session_id>/                          ← session_id = YYYYMMDD_HHMM 或 --session-id
│   ├── session.log                        ← stdout/stderr tee（追加）
│   ├── state.json                         ← completed_stages + last_passed_ckpt
│   ├── pool/                              ← 对手池环形缓冲区（若使用）
│   │   ├── pool.json
│   │   └── member_*.pt
│   └── <curriculum_parts...>/<stage>/
│       ├── checkpoint.pt                  ← 通过时保存
│       ├── checkpoint.partial.pt          ← G 方案兜底副本
│       ├── checkpoint.failed.pt           ← 真实失败
│       ├── metrics.jsonl                  ← 每次迭代的 PPO/advantage 指标
│       ├── plots/                         ← 注意力转储（c2h/h2c 等）
│       ├── replays/                       ← 评估 replay 转储
│       └── diagnostics/eval_it<N>.txt
└── replays/go_tests/                      ← Go 测试 replay 转储（与 session 无关）
```

续跑方式：传入相同的 `--session-id`，`state.json` 驱动
`completed_stages`，`train_stage` 跳过已通过的阶段。
`--fresh` 忽略已有状态。

## ELO 评级（C 方案，已于 6ffef04 + 14f1ed8 落地）

`pass_winrate` 仍是默认门控机制，但阶段可通过同时设置
`[progression] pass_elo_delta` 和 `[eval] opponent = "pool"` 选用 ELO delta 门控。
Pool 是每 session 维护的 AlphaStar 风格历史检查点环形缓冲区（默认容量 10），
存放于 `<session_dir>/pool/`。每次阶段通过都会将检查点加入 pool；
后续基于 pool 的阶段使用 softmax 加权的 ELO 接近度偏好从中采样对手，
并在每局后对双方应用双向国际象棋风格 ELO 更新。

阶段级门控逻辑（runner）：
- 若设置了 `pass_elo_delta` 且评估对手为 "pool"：
  连续两次评估中 `current_elo - stage_start_elo >= pass_elo_delta` 时通过。
- 否则：连续两次 `winrate >= pass_winrate` 时通过（A 方案），
  达到 max_iterations 时触发 G 方案部分通过兜底。

pool 类参见 `training/opponent_pool.py`，每局更新参见 `training/rollout.py`
的 `update_pool_elo`，完整门控流程参见 `docs/training/promotion.md`。

## 参见

- `docs/decisions/README.md` — Stage A 引擎 bug 和 reward shaping / per-binding 加载设计决策的 ADR
- `docs/current/engine/README.md` — 引擎内部原理，包括 per-binding 角色文件加载
- `docs/network/README.md` — 智能体架构，dropout
- `docs/training/legacy/` — 前 Go 引擎时代的历史/已废弃训练计划；保留供考古，不代表当前规范
