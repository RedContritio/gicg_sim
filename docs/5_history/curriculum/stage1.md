> **ARCHIVED 2026-05-16(P1-T7)** — Stage 1 PASS(PPO BC→PPO + AZ pure self-play),curriculum CLOSED per ADR-0009/0010,详见 [`plan.md`](plan.md) 顶部 note。

---

---
stage: 1
status: PASS (PPO BC→PPO + AZ pure self-play)
last_updated: 2026-04-26
runs: s017 (PPO BC→PPO), s058-s060 (AZ multi-seed n=3)
---

# Stage 1 — 加回骰子随机性

**PPO 状态: PASS** (s017, BC→PPO, indicative single-seed)
**AZ 状态: PASS (indicative)** (s058-s060, multi-seed n=3) — vs random 0.938 ± 0.063

**关键发现 (2026-04-26 修订,F1 backfill 后)**:
- ✅ AZ pure self-play 在弱 baseline (vs random) 直接 PASS,PPO pure-PPO 失败 — search 替代 BC bootstrap
- ❌ **AZ pure self-play vs F1-D2 = 0.125 同 PPO pure-PPO 水平** — strong adversarial baseline 下 search 不够,self-play collapse 是结构性问题
- 之前"AZ 不需 BC"的结论只对弱 baseline 成立。突破 F1-D{2,3} ceiling 仍需 BC warm-start 或其他机制 (asymmetric self-play / fixed-opponent rollout / reward shaping)

## Spec

Stage 0 同 + 移除 `fix_dice` (骰子每回合随机 roll)。

## 结果对照

### PPO BC→PPO (s017, n=64 single seed)

| baseline | wr |
|---|---|
| vs random | 0.969 |
| vs F1-D1 | 0.719 |
| vs F1-D2 | **0.500** |
| vs F1-D3 | 0.406 |

训练: BC pretrain (s016d, soft_match 73%) → PPO fine-tune 500 iter (lr=1e-4, entropy=0.003)。

### AZ pure self-play multi-seed (s058-s060, n=3)

完整 ladder (含 2026-04-26 send_matchup F1 backfill):

| seed | random | mcts_50 | mcts_100 | mcts_200 | F1-D1 | F1-D2 | F1-D3 |
|---|---|---|---|---|---|---|---|
| s058 (42) | 0.875 | 0.9375 | 0.6875 | 0.3125 | 0.250 | 0.125 | 0.0625 |
| s059 (43) | 1.000 | 1.000 | 0.875 | 0.500 | 0.250 | 0.125 | 0.0625 |
| s060 (44) | 0.9375 | 0.875 | 0.875 | 0.3125 | 0.250 | 0.125 | 0.0625 |

| baseline | mean ± std (n=3) |
|---|---|
| vs random | **0.938 ± 0.063** |
| vs mcts_pure_50 | 0.938 ± 0.063 |
| vs mcts_pure_100 | 0.812 ± 0.108 |
| vs mcts_pure_200 | 0.375 ± 0.108 |
| vs F1-D1 | 0.250 ± 0.000 |
| **vs F1-D2** | **0.125 ± 0.000** |
| vs F1-D3 | 0.063 ± 0.000 |

训练 wall ~20-22min per seed。配置 `configs/s058_az_stage1_baseline.toml` 等
(同 Stage 0 `s055` except 去 fix_dice → 默认随机 roll)。

## Go/No-go (AZ) — dual judge

| 判据 | 结果 |
|---|---|
| curriculum_plan 官方 (vs random ≥ 0.85) | **PASS** (0.938 ± 0.063) |
| F1-D2 stricter (≥ 0.40,Stage 3 用) | **FAIL** (0.125 ± 0.000) |

**Verdict: dual** — 弱 baseline PASS,strong baseline FAIL,与 Stage 0 同 plateau (vs F1-D2 = 0.125)。

## 关键观察 — 与 PPO 对照

| 项 | PPO Stage 1 | AZ Stage 1 |
|---|---|---|
| pure self-play | **FAIL** (s009-s014 vs F1-D2 < 0.13) | **PASS** (vs random 0.938) |
| BC warm-start | PASS (vs F1-D2 = 0.500) | (未测) |
| 训练 wall | ~10min per seed (500 iter PPO) | ~20-22min per seed (200 g AZ) |

PPO pure-PPO 失败的根因 (诊断已完整,见 registry s009-s014 row): self-play collapse + value scale + opponent overfit。这些问题在 AZ 框架下都不出现:
- AZ 用 MCTS visit count 作 policy target,不存在 PPO 的 ratio clip pathology
- AZ value head 学终局 z (固定 ±1) 不存在 reward scale 问题
- AZ self-play 用 arena ckpt 替换避免 dual-policy 退化

## 下一步

**推 Stage 2 AZ baseline (s061-s063)** — 同 spec + partial obs (obs_mask hide enemy dice/hand),验证 AZ + IS-MCTS determinization 在 hidden info 下是否仍 work。

## 参考

- Plan: [`plan.md`](plan.md) Stage 1 章
- Memory: `project_bc_warmstart_progress` (PPO), `project_az_stage1_baseline` (AZ s058-s060)
