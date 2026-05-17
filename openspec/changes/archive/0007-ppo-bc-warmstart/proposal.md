# PPO BC warm-start (Stage 1)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0007-ppo_bc_warmstart.md` at P1-T1)
**Original date:** 2026-04-25
**Original status:** Accepted plan (后续 BC warm-start 整体范式被 ADR-0009 closure 否决)
**Supersedes:** —
**Superseded by:** —

## Why

`adr-0008-rl_paradigm_pivot` 提出 BC warm-start 是 dominant lever;s009-s014 6 run 穷举证实 Stage 1
pure PPO structural 不行(F1-D2 = 0.07)。需在 PPO 栈用 F1-D2 dice_greedy 作 teacher,BC 预训 PPONet
然后 PPO fine-tune,在 Stage 1 上达成 vs F1-D2 ≥ 0.40 (Stage 1 Go/No-go)。

和 r009_plan (AZ 路径) 关键区别:
- **stack**: PPO (curriculum 栈) vs AZ
- **network**: `training/ppo/net.py::PPONet` (MLP trunk + policy/value 双头) vs AZ `Agent` (attention/struct_readout)
- **fine-tune**: PPO clip loss vs AZ MCTS
- **scope**: Stage 1 (random dice) vs full 2v2

**不追求超过 F1-D2** — 与 r009 同,只是 warm-start。PPO fine-tune 目标从 F1-D2 ceiling (vs F1-D2 ~0.50)
突破到 > 0.60。

## What

6 关键设计决策:

- **D1 Teacher trajectory collection**:F1-D2 + dice_greedy(s007 验证最强 greedy)。两种起点每局
  随机选 50/50:F1-D2 self-play(双方 F1-D2,只记一侧 teacher) / F1-D2 vs F1-D1(对手 F1-D1 产生
  不同棋局)。每局 seed 独立,`fix_dice=None`,`max_rounds=3`。目标 50k decisions ≈ 1700 局 ≈ 42 min。
  存储 `npz` flat arrays 于 `artifacts/<ts>_s015_bc_data/dataset.npz`。
- **D2 网络**:复用 `PPONet` (d_model=256, trunk 2 层 MLP)。不改结构;若 BC match rate < 60% 再
  考虑加大。
- **D3 BC loss**:policy head CE to teacher argmax(legal_mask 应用到 logits);value head MSE to
  `terminal_z`(episode 最终结果,teacher 视角 ±1/0,MC estimate 不 TD bootstrap)。
  `L_total = L_policy + 0.1 * L_value`(value_coef 0.1)。
- **D4 BC pretrain 超参**:Adam / LR 3e-4(PPO 同值) / batch 256 / 10 epochs / LR linear decay 到
  3e-5 / grad clip max_norm 0.5。
- **D5 PPO fine-tune 衔接**:加载 BC ckpt state_dict;**降 entropy_coef 0.01 → 0.003**(BC 已 commit
  到 teacher distribution);**降 lr 3e-4 → 1e-4**(防 warm-start 被早期 PPO gradient 冲掉);
  `rollout_opponent='F1-D1,F1-D2'` mix;`n_iterations 500-1000`。
- **D6 Go/No-go 判据**:
  - BC 阶段 held-out 100 局:match rate ≥ 80% → PPO fine-tune;60-80% → 加大 d_model/数据;< 60% →
    停诊断 obs/网络缺陷
  - PPO fine-tune vs F1-D2 n=64:≥ 0.40 → Stage 1 PASS;0.25-0.40 → marginal 加 iter;< 0.25 → fine-tune
    破坏 BC,调 lr/entropy/KL penalty

## Affected specs

- `paradigm-ppo` (待建,P1+)
- `paradigm-bc` (待建,P1+)
