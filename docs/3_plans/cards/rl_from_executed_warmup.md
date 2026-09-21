# 从 executed-warmup 出发的等预算 RL

2026-09-17 深夜启动。前提：`executed` 模仿目标已带来首个显著收益
（[历史报告](../../5_history/executed_objective_20260917.md)，warmup3 对 F1-D2
41.36% [35.0,47.7]，配对 +8.18pp [+0.45,+15.45]）。本实验检验在该更强初始化上
做普通全网络策略梯度 RL（无规则监督、无残差）能否继续逼近 D2。

## 设计

- 初始：warmup4（512 局/4000 步 executed；若其缩放配对差 ≤ 0 则退回 warmup3）。
- 算法与 run 000045 完全一致：8 轮 × 128 局、F1-D2 对手、dev F1-D2 55 场景、
  temperature 0.5、value baseline、lr 1e-5、anchor KL 0.02、clip 0.2、
  `native_variants.toml` 50% 混合、全网络可训练。
- 判读：dev 轨迹相对 warmup4/3 的初始 dev 是否上升；最终 ckpt 在新 seed
  110 场景原生面板 + 变体面板 vs F1-D2 与初始配对。下界 > 0 才算 RL 有收益。
- 产物根：`artifacts/rl_from_executed_20260917/`（56）。

## 固定协议

- 指纹 `afa1cdcd…`；`tools/` 改动（imitation_loss/train/audit_fit）不在覆盖内。
- 种子：RL 96200 / dev 96290；确认面板 96210（原生）与 96220（变体 heldout）。
- 与 000045 的差异只有初始 ckpt 与 seed；这是刻意的单变量对照。
