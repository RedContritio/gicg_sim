# 训练循环

> 相关决策：`decisions.md` D4（无对手池）、D5（±1 奖励）、
> D6（纯 AZ + 自举监控 + 升级方案）、D10（领域随机化）。
>
> 本文讲**算法流程**（selfplay → buffer → train → arena）。进程/IPC
> 架构（worker pool、inference server、虚损失 batching）见
> [`parallel_inference.md`](parallel_inference.md)。

## 总体架构

```
┌─────────────────────────────────────────────────┐
│                 Self-play worker(s)              │
│                                                  │
│  for game in infinite_stream:                    │
│      setup = sample_match_setup(config)          │
│      trajectory = play_game(network, setup)     │
│      replay_buffer.extend(trajectory)            │
└──────────────────┬──────────────────────────────┘
                   │  (state, π_mcts, z) tuples
                   ▼
┌─────────────────────────────────────────────────┐
│                 Replay Buffer                    │
│              ring buffer, 500k positions          │
└──────────────────┬──────────────────────────────┘
                   │  minibatches
                   ▼
┌─────────────────────────────────────────────────┐
│               Training worker                    │
│                                                  │
│  for step in infinite_stream:                    │
│      batch = buffer.sample(batch_size)           │
│      loss = compute_loss(network, batch)        │
│      loss.backward(); optimizer.step()           │
│      periodically: save_ckpt(), run_arena()     │
└─────────────────────────────────────────────────┘
```

**自对弈与训练并行运行**，通过回放缓冲区连接。标准 AlphaZero 架构。

## 自对弈 worker

### 单局游戏流程

```python
def play_game(network, config, rng) -> list[TrainingExample]:
    # D10: 领域随机化 — 每局独立采样对局配置
    setup = sample_match_setup(config, rng)
    env = GicgEnv(
        team_0=setup.team_0,
        team_1=setup.team_1,
        card_pool=setup.card_pool,
        seed=rng.randint(0, 2**31),
    )
    env.reset()

    trajectory = []  # (obs, pi_mcts, turn_of_actor)

    step_idx = 0
    while not env.done:
        obs = env.obs()

        # 在根节点加 Dirichlet 噪声，基于温度采样的 MCTS
        mcts_result = mcts_search(
            env, obs, network,
            n_rollouts=config.n_rollouts,
            dirichlet_alpha=config.dirichlet_alpha,
            dirichlet_eps=config.dirichlet_eps,
        )

        # 基于温度的动作采样
        if step_idx < config.tau_threshold:
            action = sample_by_visits(mcts_result.visits)  # tau=1
        else:
            action = argmax(mcts_result.visits)  # tau=0

        trajectory.append(TrainingExample(
            obs=obs,
            pi_mcts=normalize(mcts_result.visits),
            turn=env.current_player,
            is_discovery=mcts_result.is_discovery,
        ))

        env.step(action)
        step_idx += 1

    # 将 z 反向标注到每条轨迹条目
    z = _z_from_winner(env.winner)
    for ex in trajectory:
        ex.z = z if ex.turn == 0 else -z  # 视角翻转

    return trajectory
```

### 领域随机化（D10）

```python
def sample_match_setup(config, rng) -> MatchSetup:
    team_size = rng.randint(config.team.size_min, config.team.size_max + 1)

    team_0 = rng.sample(config.team.char_pool, team_size)
    if config.team.mirror:
        team_1 = team_0
    else:
        team_1 = rng.sample(config.team.char_pool, team_size)

    return MatchSetup(
        team_0=team_0,
        team_1=team_1,
        card_pool=config.cards.card_pool,
    )
```

**每局游戏使用不同的配置**，在对局配置的分布范围内采样。网络能看到所有队伍组合和所有卡池，并学习跨配置的泛化能力。

### 对局配置格式

替代旧的 PPO 阶段配置。示例：

```toml
# configs/match_1v1_L12.toml
[team]
size_min = 1
size_max = 1
char_pool = ["赤蝶", "墨客", "猫咪", "刻师傅", "天星"]
mirror = false

[cards]
mode = "shared"
card_pool = ["碌碌无为", "佛跳墙", "美味烧鸡", "占星", "诅咒"]

[mcts]
n_rollouts = 400
c_puct = 1.4
dirichlet_alpha = 0.3
dirichlet_eps = 0.25
tau_threshold = 15

[train]
batch_size = 256
lr = 1e-3
weight_decay = 1e-4
buffer_size = 500_000
train_ratio = 4  # 每局自对弈游戏对应的训练步数
min_buffer_before_training = 5000

[arena]
eval_interval_games = 500
eval_n_games = 40
replacement_threshold = 0.55
```

一个配置描述的是**游戏配置的分布**，而非单一场景。不同场景的配置可以顺序执行（类似 PPO 的课程学习，但每个阶段是完整的独立运行，而非门控），也可以在整个训练过程中只使用一个配置。

## 回放缓冲区

简单的环形缓冲区，支持可选的加权采样：

```python
class ReplayBuffer:
    def __init__(self, capacity: int):
        self.capacity = capacity
        self.entries = []
        self.priorities = []  # 若启用 D13 Mode A
        self.write_idx = 0

    def extend(self, trajectory, trajectory_priority=1.0):
        for ex in trajectory:
            if len(self.entries) < self.capacity:
                self.entries.append(ex)
                self.priorities.append(trajectory_priority)
            else:
                self.entries[self.write_idx] = ex
                self.priorities[self.write_idx] = trajectory_priority
                self.write_idx = (self.write_idx + 1) % self.capacity

    def sample(self, batch_size) -> list[TrainingExample]:
        if self.use_priority:
            probs = np.array(self.priorities) / sum(self.priorities)
            idxs = np.random.choice(len(self.entries), batch_size, p=probs)
        else:
            idxs = np.random.randint(0, len(self.entries), batch_size)
        return [self.entries[i] for i in idxs]
```

**轨迹优先级**（D13 Mode A）：包含至少一个"发现事件"（来自 MCTS 检查点 argmax 比较）的轨迹会获得大于 1.0 的优先级乘数，使其中的局面被更频繁地采样。默认乘数为 3-5 倍。

**缓冲区容量**：50 万局面是合理的起点。每局游戏约 30 个局面（含骰子时约 100 个），可存储约 5000-15000 局游戏的数据。较旧的数据按 FIFO 顺序淘汰。

## 训练 worker

### 训练步骤

```python
def train_step(network, batch):
    obs = stack([ex.obs for ex in batch])
    pi_target = stack([ex.pi_mcts for ex in batch])
    z_target = stack([ex.z for ex in batch])

    logits, value = network(obs)

    value_loss = F.mse_loss(value, z_target)
    policy_loss = -(pi_target * F.log_softmax(logits, dim=-1)).sum(-1).mean()
    l2 = sum((p ** 2).sum() for p in network.parameters()) * config.weight_decay

    loss = value_loss + policy_loss + l2

    optimizer.zero_grad()
    loss.backward()
    optimizer.step()

    return {
        "total": loss.item(),
        "value": value_loss.item(),
        "policy": policy_loss.item(),
    }
```

### 训练速率

`train_ratio = 4`：每完成一局自对弈游戏，执行 4 步训练（对缓冲区中的随机批次）。这是标准 AZ 比率——过高会导致网络过拟合早期缓冲区内容；过低会使自对弈数据产生速度超过学习速度。

### 学习率

初始使用固定 `lr = 1e-3`（AdamW）。国际象棋中的 AlphaZero 使用学习率调度（阶梯衰减），但我们可以先从固定值开始，按需再添加调度策略。

## Arena 评估

定期将当前"训练中"的网络与保存的"冠军"网络对战 N 局进行评估：

```python
def arena_eval(current, champion, config):
    wins = 0
    for i in range(config.eval_n_games):
        env = make_env(sample_setup(config))
        who_is_current = i % 2  # 交替先后手
        result = play_match(env, current, champion, who_is_current)
        if result.winner == who_is_current:
            wins += 1
    return wins / config.eval_n_games
```

如果 `wins / N > config.replacement_threshold`（默认 0.55），当前网络**取代冠军**。否则保留冠军，训练继续使用相同的对手参考。

**注意**：arena 评估直接使用网络（不做 MCTS，或使用比自对弈更小的搜索预算）。基于 MCTS 的网络评估更耗时但更准确——根据计算预算调整。

**回放缓冲区在检查点替换时不重置**。由前任冠军生成的旧数据仍然是有效的训练信号。

## 自举监控（D6）

每 N 局自对弈游戏，计算一次**连击发现率**指标：

```python
def compute_combo_discovery_rate(recent_trajectories):
    total = len(recent_trajectories)
    with_discovery = sum(
        1 for traj in recent_trajectories
        if any(ex.is_discovery for ex in traj)
    )
    return with_discovery / max(total, 1)
```

"`is_discovery`"来自 MCTS 检查点 argmax 比较（D13）：在自对弈时，如果最终最优动作与早期检查点处的最优动作不同，该步骤会被标记。

每 500 局游戏记录一次该指标。如果长时间保持为 0（例如超过 5000 局无任何发现），说明自举已陷入停滞，触发 D6 升级方案。

## D6 升级方案（被动触发，默认关闭）

按优先级顺序：

### 升级 1：提高 Dirichlet 探索噪声

```python
config.dirichlet_alpha = 0.5  # 从 0.3 提升
config.dirichlet_eps = 0.4    # 从 0.25 提升
```

拓宽根节点探索。成本最低的干预手段。一旦发现率 > 0.01，恢复为默认值。

### 升级 2：启用 D13 Mode B（发现时深度搜索）

检测到发现事件时，将搜索扩展 30% 的 rollout 次数：

```python
if mcts_result.is_discovery:
    extra_rollouts = int(config.n_rollouts * 0.3)
    run_additional_rollouts(extra_rollouts)
```

在提交该动作前，细化已发现分支的 Q 值估计。

### 升级 3：启发式 rollout 用于叶节点估值

将叶节点估值从 `network.value_forward` 临时切换为贪心最大伤害 rollout：

```python
def leaf_eval_heuristic(env) -> float:
    # 使用简单启发式（选择最高伤害动作）向前推演
    # 直到游戏结束或达到最大深度，以结果作为价值
    depth = 0
    while not env.done and depth < 40:
        legal = env.get_legal_actions()
        action = pick_max_damage_action(legal, env)
        env.step(action)
        depth += 1
    return p0_value(env.winner) if env.done else 0.0
```

相比随机 rollout 提供更密集的信号；在训练早期网络接近随机时，比网络估值更快。一旦连击出现，恢复为网络价值估值。

### 升级 4：有监督的连击示例

最后手段。手工编写或从人类对局中挖掘 5-20 条典型连击序列，以高权重的有监督 (state, pi_mcts, z) 元组注入回放缓冲区。这本质上是在 AZ 之上叠加模仿学习。

## 检查点管理

- 每 `save_interval_games` 局（例如 1000 局）保存一次训练网络
- 每次 arena 评估后也保存（替换前的快照）
- 保留滚动历史：最近 10 个检查点 + 每 100 局的快照
- 布局：`artifacts/az/<run_id>/ckpts/*.pt`

## 需要记录的指标

每训练步：
- `loss/total`、`loss/value`、`loss/policy`、`loss/l2`
- `grad_norm`
- `lr`

每局游戏：
- 游戏长度（步数）
- 胜者
- 实际使用的 MCTS rollout 次数（固定值，除非触发 Mode B 升级）
- 每步的 `is_discovery`（用于连击发现率）

每 500 局游戏：
- 缓冲区大小
- `combo_discovery_rate`
- 当前冠军检查点的"年龄"（距上次替换已过的局数）

每次 arena 评估：
- 对冠军的胜率
- 是否发生替换
- 各场景的游戏数分解（若为多场景）
