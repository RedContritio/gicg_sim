---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
parent: ./README.md
---

# CFR runs

> CFR paradigm 在 GICG 上只有一个 production run(r008)+ 配套
> unit / smoke。详细见 [`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md) r008 行。

## 2026-04-23 ~ 04-24 r008 Deep CFR prototype

| Field | Value |
|---|---|
| ID | r008 |
| Label | `r008_cfr_prototype` |
| Started | 2026-04-23 01:30 |
| Wall | 32.7h(117673s) |
| Cfg | fixed 2v2 team(赤蝶+墨客 vs 猫咪+刻师傅),200 iter × 32 traversal, d_model=64, n_cross_layers=2 |
| Algorithm | OS-MCCFR + B1 canonical fixes(reach_q_prefix per commit `e05b713` + Def.4 非采样 σ(a*) per commit `54f6c35`); Kuhn Nash 收敛 unit test 层 PASS |
| Launch | `tools.run_cfr --preset r008_cfr_prototype --n-workers 4 --seed 42` |
| Final gauntlet(iter 199)| **0.40 vs random / 0.00 vs mcts_50/100/200 / 0.00 vs greedy F1-D1 dice_greedy** |
| Early-ckpt sweep | iter 20=1.00 / 40=0.80 / 60=0.70 / 80=0.60 / **100=0.00** / 120=0.30 / 199=0.40 |
| Status | **done, failed**(2026-04-24)|

**Verdict**: iter 199 worse than iter 20 init noise;current config Deep CFR
不训有用策略。下一轮若有 SHOULD 加:per-iter gauntlet + advantage_reset_each_iter=True
+ d_model ≥ 256。但 user 评估 2026-05-12 把 NFSP / Deep CFR redo 一并归入 closed
(memory `project_rl_routes_closure_2026_05_12`)→ 无下一轮。

## Unit / smoke 测试(代码仍保留)

当时 `training/cfr/` 的实现现位于 [`training/paradigms/cfr/`](../../../training/paradigms/cfr/)；历史验收记录为 16 pytest 全 PASS，涵盖:

- Kuhn poker Nash 收敛(canonical sanity check)
- OS-MCCFR reach_q_prefix correctness(B1 修复 regression)
- Def.4 non-sampled σ(a*)(B1 修复 regression)
- Reservoir buffer overflow/underflow
- Traversal mixin Mock env 端到端
- ParallelTrainer worker fanout

代码保留可重现 — 若未来 paradigm reopen(eg. new evidence Deep CFR can train GICG-class
imperfect-info games at reasonable compute),可直接复用 framework。

## 不 actionable 的 follow-up(知识保留)

per memory `project_r008_postmortem` next-round proposal,**未执行**(closure):

- `advantage_reset_each_iter=True` — 每 iter 重置 advantage replay,避免老 traj 污染
- `d_model` 64 → 256+ — capacity 不足是 hypothesis 之一
- per-iter gauntlet — 早发现 iter 100 那种局部 collapse
- value head opt 独立 — value 乐观可能来自 shared trunk gradient leak
