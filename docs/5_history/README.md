# 5_history/ — 冻结历史

> **冻结区**。日期烙印的文档:postmortem / review / audit / evidence / ablation / 已废 epoch。

## 子目录

| 目录 | 内容 |
|---|---|
| [`postmortems/`](postmortems/) | run / 系统 / bug 的事后复盘 (按 date + run-id 命名) |
| [`reviews/`](reviews/) | 第三方 / 内部审计、review action plan |
| [`audits/`](audits/) | 单子系统 deep audit (env / determinize / generalization) |
| [`evidence/`](evidence/) | 一次性 benchmark / 决定性证据 (bench_snapshot, mcts_vs_policy, 2026-09-11 训练重置清单三份 JSON) |
| [`ablations/`](ablations/) | ablation 量化矩阵 (r001-r006, Stage 3 PPO closure) |
| [`decisions_legacy/`](decisions_legacy/) | 早期 D5-D13 引擎决策链,作为档案保留 (未来 ADR 走 `2_decisions/`) |
| [`eras/`](eras/) | 已废弃 epoch 的整体归档 (`ppo_pre_az/` = r001 之前的老 PPO) |

## 编辑规则

- **不再编辑**。一份 history 文档反映"当时知道的事实"
- **事实纠错**允许,格式 `> 更正 (YYYY-MM-DD): ...`,加在原文附近
- **后续进展不改旧文档**,写新的 (`openspec/specs/` 或 `3_plans/`) 并在旧文顶部加 `> Superseded by: ...`
- **命名保留时间/run-id 烙印** (e.g. `r008_postmortem.md`, `c1v6_plan.md`),便于 grep
