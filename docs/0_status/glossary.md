---
last_updated: 2026-09-14
status: LIVE
---

# Glossary — 术语速查

> 跨文档、规格和提交记录的高频术语。新人遇到不认识的词来这查。

## 项目阶段

| 词 | 含义 |
|---|---|
| **PPO pre-AZ era** | r001 之前的老 PPO 训练栈,phase{0-5} 课程,2026-04-14 前。归档在 `5_history/eras/ppo_pre_az/` |
| **AZ era** | 2026-04-14 PPO→AZ 迁移决策后,r001-r008 + C1 系列 |
| **Curriculum era** | 2026-04-24 paradigm pivot 后,RL Curriculum 5-stage 路线 |

## Run 命名

| 词 | 含义 |
|---|---|
| **r001 ... rNNN** | production-style training run,multi-hundred games + arena + gauntlet |
| **s001 ... sNNN** | short validation / smoke / bench / ablation run |
| **artifacts/YYYYMMDDHHMM_\<NNNNNN\>_\<label\>/** | 2026-05-18 后 run 输出位置；每个目录自带 metadata、配置快照、ckpts 与日志 |
| **registry** | `python -m tools.runs.list` 扫描 `artifacts/*/metadata.toml`；pre-redesign r/s 记录见 `5_history/runs_pre_redesign_2026_05_17.md` |

## 训练栈

| 词 | 含义 |
|---|---|
| **AZ** | AlphaZero 风格,IS-MCTS + 共享主干网络,在 `training/paradigms/az/` |
| **CFR** | Deep CFR,在 `training/paradigms/cfr/`,r008 失败后冻结 |
| **PPO (Curriculum era)** | Stage 0-3 用的 PPO,现保留在 `training/paradigms/ppo/` |
| **BC** | Behavior Cloning warm-start,F1-D2 teacher 数据 |
| **core** | `training/core/`,算法无关基础 (actor / network / buffer / inference / eval / matchup) |

## Curriculum

| 词 | 含义 |
|---|---|
| **Stage 0** | 1v1 mirror + 无卡 + 无反应 + 定骰 + 完全可观测 + 稠密 reward |
| **Stage 1** | + 骰子随机 |
| **Stage 2** | + partial observability |
| **Stage 3** | + 卡牌 (closure 中) |
| **Stage 4** | + 元素反应 |
| **Stage 5** | + team_size=2,full game |

## Scenario

| 词 | 含义 |
|---|---|
| **F1-D{N}** | F1 baseline,depth N greedy minimax (D1=1-ply, D2=2-ply, D3=3-ply) |
| **F1-D2 dice_greedy** | 当前 strongest hand-crafted baseline,vs mcts_200 = 0.90 |
| **mcts_{N}** | random rollout MCTS,N rollouts/decision |
| **random_1v1 / random_team** | char_pool=5, team_size=1/2 random sample per game |

## 网络结构 (AZ)

| 词 | 含义 |
|---|---|
| **structural sid** | 每局固定 sid 0..65 (HP/energy/alive/active × chars + dice + alive_count),不 shuffle |
| **机制性 sid** | shuffle (shields, buffs, summons, attachments, DSL counter),反 ID 原则 |
| **struct_readout** | 直接从 66 维 structural values gather,绕过 cross-attn pool 零空间 |
| **C18 定理** | pool 后 state_vec 是置换不变统计量 → loss 对 cross-attn 内部分布零梯度 |
| **lambda (value_mix)** | MCTS leaf eval 中 net_value 与 rollout_value 混合系数 |

## 命令

| 词 | 含义 |
|---|---|
| **eval_service** | 全局 localhost TCP gauntlet evaluator（默认 `localhost:9100`），需要时在 run 前启动 |
| **gauntlet** | vs N-tier baseline 的 win rate 评估 (random / F1-D1/D2/D3 / mcts_50/100/200) |
| **arena** | 历史 AZ 新旧 ckpt 对战接口；旧 `training/az/arena.py` 已移除，当前评估见 `training/core/eval/` 与 `training/core/matchup/` |
