---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
paradigm: cfr
---

# CFR paradigm dossier

> **Status**: **CLOSED**
>
> **One-line verdict**: r008 Deep CFR prototype iter 199 collapse(40% vs random /
> **0/10 vs everything**, including greedy F1-D1),比 iter 20 初始化还差;
> strat_loss 1.3→1.045 假象收敛,loss 与 policy quality 彻底脱钩。
> user 2026-05-12 评估扩展 closure 含 NFSP / Deep CFR redo 一并 closed。

## Overview

CFR(Counterfactual Regret minimization)是 2026-04-23 ~ 04-24 期单 run prototype
(r008),paradigm change 自 AZ 路线 r007 killed 之后。核心轨迹:

1. **r008 Deep CFR prototype**(2026-04-23,fixed 2v2 team,d_model=64,200 iter):
   - OS-MCCFR 带 B1 完整 canonical 修复(reach_q_prefix + Def.4 非采样 σ(a*))
   - Kuhn Nash 收敛 end-to-end 验证(unit test 层 PASS)
   - **GICG 上 32.7h wall, iter 199 gauntlet 0.40 vs random / 0/10 vs mcts/greedy**
2. **iter 100 诊断**:Switch fixation(~50% 动作选 Switch)+ value head 乐观
   (终局前 v=+0.2 但实际 0/10 输);strat_loss 视觉收敛 ≠ policy quality。
3. **Closure 扩展**(user 2026-05-12):NFSP / Deep CFR redo 也归入 closed,
   per memory `project_rl_routes_closure_2026_05_12`。

## Verdict tree

```
Kuhn poker(unit test)
└── OS-MCCFR B1 canonical implementation → Nash 收敛 PASS

GICG 2v2(r008 prototype)
├── iter 20 → 1.00 vs random(init noise)
├── iter 40-80 → 0.6-0.8 vs random(transient peak)
├── iter 100 → 0.00 vs random(Switch fixation + value 乐观)
├── iter 120 → 0.30 vs random(partial recover)
├── iter 199 → 0.40 vs random,0/10 vs mcts/greedy
└── strat_loss 1.3→1.045 假象收敛 → 现状 config Deep CFR 不训有用策略
```

## Key data points

| Iter | Wall(累计) | vs random | vs mcts_50/100/200 | vs greedy F1-D1 |
|---|---|---|---|---|
| 20 | ~3.3h | 1.00 | — | — |
| 100 | ~16h | **0.00** | — | — |
| 120 | ~20h | 0.30 | — | — |
| 199 final | 32.7h | 0.40 | 0/10 / 0/10 / 0/10 | 0/10 |

完整诊断 → memory `project_r008_postmortem`。

## Subdirectories

- [Runs](./runs.md) — r008 single run(no follow-up)
- [Postmortems](./postmortems.md) — r008 collapse 诊断

(无 ablations.md / architecture.md — single-run paradigm,无 architecture iteration。)

## Cross-references

**Archived OpenSpec changes**: 无 CFR-specific archived change(CFR detour
未走 OpenSpec 流程,直接 in-repo 实现 + r008 实验后 closure)。决策上下文
看 [`openspec/changes/archive/0008-rl-paradigm-pivot/`](../../../openspec/changes/archive/0008-rl-paradigm-pivot/)
(PPO → AZ pivot 时期 CFR detour 提出)和
[`openspec/changes/archive/0006-training-layout/`](../../../openspec/changes/archive/0006-training-layout/)
(`training/cfr/` 三层 layout decision)。

**Frozen history**:

- 暂无 dedicated 5_history CFR postmortem doc(complete picture 在 memory
  `project_r008_postmortem` 中);若未来重启 CFR 路线,SHOULD 把 memory 内容
  落 [`docs/5_history/postmortems/r008_cfr_postmortem.md`](../../5_history/postmortems/)
- 训练 layout decision:
  [`openspec/specs/training-architecture/`](../../../openspec/specs/training-architecture/)
  (含 framework / az / cfr 三层 split,详 ADR-0006)

**Run registry**:
[`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md) r008 行(single run)。

**Memory**:

- `project_r008_postmortem` — r008 iter 199 collapse 完整诊断(canonical 来源)
- `project_rl_routes_closure_2026_05_12` — user 评估扩展 closure 含 NFSP / Deep CFR redo
- `project_rl_paradigm_pivot` — PPO → AZ paradigm pivot 决策上下文(CFR 在此期间作 detour 提出)

**Code**:

- [`training/paradigms/cfr/`](../../../training/paradigms/cfr/) — CFR adapter
  (P4-CFR ship,paradigm.py + collector.py + policy.py + loss.py + network.py;
  `legacy/` 子目录承载 Deep CFR traversal Mixin / reservoir / CFRAgent
  advantage/strategy/value fit 实现);16 pytest 完整,代码保留可重现
  (detour 关闭后 user 决策代码不删,作 reference)
- 入口:`python -m tools.run configs/cfr/<config.toml>`(`meta.paradigm = "cfr"`)
