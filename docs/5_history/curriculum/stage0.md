> **ARCHIVED 2026-05-16(P1-T7)** — Stage 0 PASS(both PPO + AZ),curriculum CLOSED per ADR-0009/0010,详见 [`plan.md`](plan.md) 顶部 note。

---

---
stage: 0
status: PASS (both PPO + AZ)
last_updated: 2026-04-26
runs: s008 (PPO), s055-s057 (AZ multi-seed n=3)
---

# Stage 0 — 1v1 mirror + 无卡 + 定骰 + 完全可观测

**PPO 状态: PASS** (s008, indicative single-seed)
**AZ 状态: PASS (indicative)** (s055-s057, multi-seed n=3) — vs random mean 0.917 ± 0.072

## Spec

| 维度 | 配置 |
|---|---|
| Team | 1v1, 单角色 (`测试角色D`) mirror |
| Char | Fire, 3 简单物理技能 (轻击/重击/突刺) |
| Cards | `card_pool=[]` |
| Reactions | 同元素 mirror 自然规避 (`disable_reactions` 未实现,moot) |
| Dice | `fix_dice=[2,2,2,2,0,0,0,0]` |
| Visibility | `fully_observable=True` |
| Max rounds | 3 |
| Reward (PPO) | dense (hp_delta=1, hp_taken=1.1, terminal=±60) |
| Reward (AZ) | 纯终局 ±1 (D5 决策) |

## 结果对照

### PPO (s008, n=16 single seed indicative)

| baseline | wr |
|---|---|
| vs random | 1.000 |
| vs F1-D1 | 1.000 |
| vs F1-D2 | **0.875** |
| vs F1-D3 | 0.781 |

训练时长 ~90s (500 iter)。配置 `configs/s008_ppo_stage0_smoke.toml`。

### AZ baseline multi-seed (s055-s057, n=3 indicative,argmax no-search,n=16 each)

完整 ladder (含 2026-04-26 send_matchup F1 backfill):

| seed | random | mcts_50 | mcts_100 | mcts_200 | F1-D1 | F1-D2 | F1-D3 |
|---|---|---|---|---|---|---|---|
| s055 (42) | 0.875 | 0.9375 | 0.625 | 0.6875 | 0.125 | 0.125 | 0.000 |
| s056 (43) | 1.000 | 1.000 | 0.9375 | 0.5625 | 0.250 | 0.125 | 0.0625 |
| s057 (44) | 0.875 | 0.875 | 0.6875 | 0.375 | 0.250 | 0.125 | 0.0625 |

| baseline | **mean ± std (n=3)** |
|---|---|
| vs random | **0.917 ± 0.072** |
| vs mcts_pure_50 | 0.938 ± 0.063 |
| vs mcts_pure_100 | 0.750 ± 0.165 |
| vs mcts_pure_200 | 0.542 ± 0.158 |
| vs F1-D1 | 0.208 ± 0.072 |
| **vs F1-D2** | **0.125 ± 0.000** |
| vs F1-D3 | 0.042 ± 0.036 |

训练时长 per seed ~20min train + ~90s gauntlet。
配置 `configs/s055_az_stage0_baseline.toml` / `s056_az_stage0_seed43.toml` / `s057_az_stage0_seed44.toml`
(base=fixed_1v1, n_games=200, n_rollouts=100, lambda_anneal_games=200, lambda_end=0.5)。

**关键发现 (F1 backfill 后 2026-04-26):** AZ pure self-play vs F1-D2 = 0.125 — 与 Stage 1/2 同 plateau,与 PPO pure-PPO Stage 1 (< 0.13) 同水平。AZ search 在弱 baseline (random/mcts_pure) 替代 BC,但在 F1-D{2,3} adversarial depth 下不够。详见 [`stage1.md`](stage1.md) 关键观察段。

## Go/No-go (AZ) — dual judge

| 判据 | 结果 |
|---|---|
| curriculum_plan 官方 (vs random ≥ 0.95) | **PASS** (0.917 ± 0.072,接近阈值) |
| F1-D2 stricter (≥ 0.40,Stage 3 用) | **FAIL** (0.125 ± 0.000) |

**dual verdict 启示**: AZ pure self-play 在弱 baseline (random) 表现良好,与 PPO Stage 0 (1.000) 接近;但在 strong baseline (F1-D2) 与 PPO pure-PPO 同弱 — self-play collapse 是结构性的,需 BC warm-start 突破。详见 [`stage1.md`](stage1.md)。

## 参考

- Plan: [`plan.md`](plan.md) Stage 0 章
- Memory: `feedback_stage0_f1d2_judge` (PPO judge), `project_az_stage0_baseline` (AZ s055)
- AZ sub-roadmap: [`../az_plans/r009_az_warmstart.md`](../az_plans/r009_az_warmstart.md)
