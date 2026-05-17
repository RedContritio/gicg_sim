> **ARCHIVED 2026-05-16(P1-T7)** — Stage 2 dual verdict(curriculum PASS / F1-D2 stricter FAIL),curriculum CLOSED per ADR-0009/0010,详见 [`plan.md`](plan.md) 顶部 note。

---

---
stage: 2
status: PASS (curriculum judge) / FAIL (F1-D2 stricter judge) — dual
last_updated: 2026-04-26
runs: s020 (PPO BC→PPO), s061-s063 (AZ multi-seed n=3)
---

# Stage 2 — 加回 partial observability

**PPO 状态: PASS** (s020 BC→PPO, vs F1-D2 = 0.531)
**AZ 状态: dual** (s061-s063 multi-seed n=3) — vs random 0.917 PASS,vs F1-D2 0.146 FAIL stricter

## Spec

Stage 1 同 + `obs_mask=["enemy_dice"]` (隐藏对手 dice)。Stage 2 是 hidden info 第一次正式引入 (Stage 0/1 fully observable)。

## 结果对照

### PPO BC→PPO (s020, n=64 single seed)

| baseline | wr |
|---|---|
| vs random | 0.891 |
| vs F1-D1 | 0.750 |
| vs F1-D2 | **0.531** |
| vs F1-D3 | 0.422 |

训练: BC pretrain (s019, soft_match 66%) → PPO fine-tune,~7-8% drop vs Stage 1 (enemy dice info value)。

### AZ pure self-play multi-seed (s061-s063, n=3)

| seed | random | mcts_50 | mcts_100 | mcts_200 | F1-D1 | F1-D2 | F1-D3 |
|---|---|---|---|---|---|---|---|
| s061 (42) | 0.875 | 0.9375 | 0.5625 | 0.4375 | 0.250 | 0.1875 | 0.0625 |
| s062 (43) | 1.000 | 1.000 | 0.875 | 0.500 | 0.250 | 0.125 | 0.0625 |
| s063 (44) | 0.875 | 1.000 | 0.6875 | 0.3125 | 0.375 | 0.125 | 0.0625 |

| baseline | mean ± std (n=3) |
|---|---|
| vs random | **0.917 ± 0.072** |
| vs mcts_pure_50 | 0.979 ± 0.036 |
| vs mcts_pure_100 | 0.708 ± 0.157 |
| vs mcts_pure_200 | 0.417 ± 0.096 |
| vs F1-D1 | 0.292 ± 0.072 |
| **vs F1-D2** | **0.146 ± 0.036** |
| vs F1-D3 | 0.063 ± 0.000 |

训练 wall ~20-22min per seed。配置 `configs/s061-s063_az_stage2_*.toml`
(Stage 1 spec + obs_mask=["enemy_dice"])。

## Go/No-go (AZ) — dual judge

| 判据 | 结果 |
|---|---|
| curriculum_plan 官方 (vs random ≥ 0.65) | **PASS** (0.917) |
| F1-D2 stricter (≥ 0.40) | **FAIL** (0.146 ± 0.036) |

**Verdict: dual** — curriculum judge PASS,F1 stricter FAIL。与 Stage 0/1 同 plateau (vs F1-D2 ≈ 0.125-0.15)。

## 关键观察

vs random (0.917) 与 PPO BC→PPO (0.891) 接近,**AZ + IS-MCTS 在 partial obs + stochastic env 下能学 vs random 强 agent**,验证 IS-MCTS determinization work。

但 vs F1-D2 (0.146) 远弱于 PPO BC→PPO (0.531),与 Stage 0/1 同 ~0.125 plateau。**partial obs 不是新难度** — 真难度在 self-play collapse 下 mirror match 学不到 attack。

## 下一步

**Stage 3 AZ pure self-play (s064-s066)** — 加卡。预测 vs random PASS (≥0.65),vs F1-D2 FAIL ≈ 0.125 (与 Stage 0/1/2 同 plateau)。

"突破 PPO Stage 3 ceiling 0.34" 需 AZ + BC warm-start (significant infra work,留 next session 决策)。

## 参考

- Plan: [`plan.md`](plan.md) Stage 2 章
- Memory: `project_az_stage2_baseline` (待写)
- Stage 0/1 dual verdict 对照: [`stage0.md`](stage0.md), [`stage1.md`](stage1.md)
