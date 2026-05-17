# RL paradigm pivot — pure end-to-end → hybrid (BC warm-start + dense reward)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0008-rl_paradigm_pivot.md` at P1-T1)
**Original date:** 2026-04-24
**Original status:** Accepted (后被 ADR-0009 super-seded "BC warm-start 是 dominant lever" 假设)
**Supersedes:** —
**Superseded by:** [`../0009-rl-paradigm-pivot-terminus/`](../0009-rl-paradigm-pivot-terminus/) 把
本 ADR 核心假设否决(r010 + s067 实证)。详 design.md "后续 closure 命中" 段。

## Why

r001-r008 共 8 次训练 run,三种 paradigm(AZ naive、AZ 长程 r007、Deep CFR r008),全部在 GICG 2v2
fixed team 场景上 stuck 或 collapse。最强 run (r001) = 0.55 vs mcts_200,**低于手工 greedy F1-D2 的
0.90**。训练相对于 "不训" 是净负增益。

### 证据

| 方法 | vs mcts_200 |
|---|---|
| greedy F1-D2 dice_greedy(手工 1-ply 加 2-ply minimax) | **0.90** |
| r001 AZ 最强 run | 0.55 |
| r007 AZ 长训 final(collapse) | 0.05 |
| r008 CFR 200 iter | 0.00 |

### 结构性失败模式

1. 稀疏终局奖励 × ~300 步 episode — AZ/CFR 信用分配链过长
2. 隐藏信息 + IS-MCTS determinization 噪声 — 每 rollout 采 1 隐状态,聚合不稳
3. 大动作空间 (20-200 含骰组合) — regret 分散 / MCTS 分支因子爆炸
4. Self-play 稳定到退化吸引子(双方 Switch spam 无进展)
5. Loss 与 policy quality 脱钩(r008 strat_loss 下降但 win rate 退化)
6. 冷启动 dead zone — random init value/policy 都瞎猜,MCTS 传播噪声

### 文献调研 6 个 pattern 命中率 0/6

- Expert heuristic → IL warm-start (AlphaStar / Suphx / Coac LoCM) — ✗ 全从 random init
- Dense reward shaping for long horizon (Suphx / OpenAI Five / AlphaStar) — ✗ AZ D5 决策改纯 ±1
- Expert heuristic 作 rollout/prior (Coac / AlphaGo Lee Sedol / 本仓库 C1v2) — ✗ AZ 走 λ→1 纯 net-value
- Action abstraction (Pluribus / Coac / AlphaStar) — ✗ 20-200 full payment fan-out
- CFR-based subgame search (Pluribus / ReBeL / Student of Games) — ✗ AZ 原版 PUCT
- Oracle guiding (Suphx) — ✗ 只看 observable

我们在做的就是文献明确论证 "在这种游戏上不行" 的配置。

## What

**弃**:pure self-play from random / pure AZ with λ→1 / pure Deep CFR

**采**:渐进式混合架构,优先 P0 三件套。

### P0(立即,低风险)

1. **Greedy BC warm-start** — F1-D2 dice_greedy 生成 50k-100k self-play 轨迹(带探索温度),预训
   网络 policy/value 到 match F1-D2 argmax ≥ 80%。下限 = F1-D2 (0.90 vs mcts_200)
2. **Dense reward shaping (HP delta)** — `reward = 终局 ±1 + λ × (round-over-round 己方 HP - 对方 HP 变化)`,
   λ 从 0.3 退火到 0.05。理论依据:Suphx / OpenAI Five 显式 ablation
3. **Greedy rollout 替代 net-value leaf eval** — MCTS leaf 用 truncated greedy F1-D1 rollout 10-20
   步终局估;C1v2 已证 rollout > net-value 10×,r007 collapse 直接来自 λ→1 退火

### P1(中期)

4. Action abstraction:dice_greedy filter 思想搬进 MCTS/network,logical action 级别,分支因子降 5-10×
5. Oracle guiding:训练网络加对手 hand/dice oracle feature,退火 dropout(Suphx 架构)

### P2(重型,P0-P1 不够时)

6. CFR-based search 替代 MCTS (ReBeL / Student of Games)
7. League training (AlphaStar pool 式)

### 非决策(已评估不采)

- **纯 DMC (DouZero 风格)** — 作者本人论证 game horizon 30 步,我们 300 步,MC 方差爆炸
- **MuZero** — hidden info 下 latent state 不处理对抗性隐藏
- **ReBeL 完整实现** — public belief state 在我们隐藏组合空间下 intractable

## Affected specs

- `paradigm-az` (D5/D6 重评估)
- `paradigm-bc` (P0-1 新增)
- `paradigm-ppo` (P0 适用)
