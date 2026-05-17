---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
paradigm: ppo
---

# PPO paradigm dossier

> **Status**: **CLOSED**(by ADR-0008 paradigm pivot + ADR-0009 curriculum terminus)
>
> **One-line verdict**: Stage 3 F1-D2 ceiling = **0.344 ± 0.062**(BC→PPO 1-card fullobs,
> 30+ ablation, multi-seed n=3);F1-D2 ≥ 0.40 stricter 在当前 BC→PPO pipeline
> 物理不可达,路线 closure 后 paradigm pivot 至 AZ。

## Overview

PPO 是 2026-04 期 GICG RL 主线尝试,从 Stage 0 baseline 到 Stage 3
30+ ablation,核心结论是:

1. **Pure PPO 不收敛**(s009-s014):Stage 1 mirror + stochastic env 下 5 个
   pipeline 配置(iter / value_coef / reward_shaping / fix opp / mix opp)全 FAIL
   F1-D2 ≤ 0.125,policy 塌陷 Tune-heavy 或 opponent overfitting。
2. **BC warm-start = dominant lever**(s017+):+0.24 single-seed gain,Stage 1
   F1-D2 = 0.500 PASS;Stage 2 partial obs 0.531 PASS。
3. **Stage 3(card pool)ceiling 0.344**(s033/s039/s040 best cell,n=3 multi-seed):
   F1-D2 stricter 0.40 不可达;4 factor combo NOT additive(predict 0.45 actual 0.281)。
4. **Pivot AZ**(ADR-0008,2026-04-25):BC→PPO 路径走完,paradigm 改 AlphaZero。

PPO 代码栈保留在 [`training/ppo/`](../../../training/ppo/)(BC pretrain + PPO fine-tune)
和 [`docs/5_history/eras/ppo_pre_az/`](../../5_history/eras/ppo_pre_az/)(老 PPO era doc)。

## Verdict tree

```
PPO Stage 0 (fix_dice + 角色D mirror)
├── single-seed indicative PASS (s008 #1 F1-D2=0.875)
└── multi-seed instability (re-run #2/#3 F1-D2=0.125/0.406) → 判据升 F1-D2/D3 multi-seed

PPO Stage 1 (stochastic dice)
├── 5 pipeline configs (s009-s014) → 全 FAIL F1-D2 ≤ 0.125
└── BC warm-start (s017) → PASS F1-D2=0.500 ✅

PPO Stage 2 (partial obs)
└── BC→PPO (s020) → PASS F1-D2=0.531 ✅

PPO Stage 3 (card_pool)
├── 4-factor matrix 29 ablation × n=3 multi-seed
├── best cell (1-card fullobs F1-D2 teacher) → F1-D2 = 0.344 ± 0.062
└── F1-D2 ≥ 0.40 stricter FAIL → ADR-0009 closure → pivot AZ
```

完整 Stage 3 ablation 见 [`ablations.md`](./ablations.md)(引用
[`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md))。

## Key data points

| Milestone | Run | F1-D2 wr | Note |
|---|---|---|---|
| Pure PPO Stage 0 indicative | s008 #1 | 0.875 (n=32) | single-seed,re-run #2/#3 0.125/0.406 |
| Pure PPO Stage 1 worst | s010 | 0.062 | iter 不是根因(value_loss 淹没 policy) |
| BC warm-start Stage 1 PASS | s017 | 0.500 (n=16) | BC+PPO,8× vs pure PPO 0.062 |
| BC warm-start Stage 2 PASS | s020 | 0.422 (n=16) | partial obs 学得到 |
| Stage 3 best cell | s033/s039/s040 | **0.344 ± 0.062** | 1-card fullobs F1-D2 teacher,3-seed |
| Stage 3 multi-card | s043/s046/s047 | 0.104 ± 0.045 | full card pool plateau |

## Subdirectories

- [Runs](./runs.md) — s001-s054 PPO era run 时间序列表
- [Ablations](./ablations.md) — Stage 3 4-factor matrix 摘要(详 5_history/ablations/stage3_ppo_closure.md)
- [Postmortems](./postmortems.md) — pure PPO 失败 + Stage 3 closure 复盘 link

PPO architecture 演化复杂度低(无 paradigm-specific architecture iteration —
shared trunk + value head 标准设计),不单写 `architecture.md`;若需细节
见 [`docs/5_history/eras/ppo_pre_az/network/`](../../5_history/eras/ppo_pre_az/network/)。

## Cross-references

**Archived OpenSpec changes**(决策落点):

- [`openspec/changes/archive/0007-ppo-bc-warmstart/`](../../../openspec/changes/archive/0007-ppo-bc-warmstart/)
  — BC warm-start 引入(Stage 1/2 PASS 触发)
- [`openspec/changes/archive/0008-rl-paradigm-pivot/`](../../../openspec/changes/archive/0008-rl-paradigm-pivot/)
  — PPO → AZ pivot 决策(2026-04-25,Stage 1 pure PPO 失败后)
- [`openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`](../../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/)
  — Curriculum closure at Stage 3(F1-D2 0.344 ceiling 确认)

**Frozen history**(复盘 doc):

- [`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md)
  — 29-ablation 完整 closure 数据点
- [`docs/5_history/eras/ppo_pre_az/`](../../5_history/eras/ppo_pre_az/)
  — PPO pre-AZ era 整目录 archive(network / training / hparams / promotion)
- [`docs/5_history/curriculum/stage{0..5}.md`](../../5_history/curriculum/)
  — curriculum plan stage 详
- [`docs/5_history/curriculum/plan.md`](../../5_history/curriculum/plan.md)
  — curriculum 总 plan(已 TERMINATED via ADR-0009)

**Run registry**:
[`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md) s001-s054(PPO era,
含 Stage 0-3 ablation + s015-s020 BC pretrain)。

**Memory**:

- `feedback_ppo_multiseed_required` — s008 同 TOML 3 次 re-run 0.875/0.125/0.406,
  single seed 不作强度判据
- `project_stage3_full_diagnosis` — Stage 3 30+ ablation 完整诊断
- `project_bc_warmstart_progress` — BC warm-start 提升路径
- `project_rl_paradigm_pivot` — paradigm pivot 决策上下文
- `reference_ppo_stack` — PPO 栈索引(目录 / 启动命令 / hyper defaults)

**Code**:

- [`training/paradigms/ppo/`](../../../training/paradigms/ppo/) — PPO adapter
  (P4-T1 ship + P5-D legacy mv;FU-W4-PPO 后 `legacy/` retired via `2e5bc6f`)
- [`training/paradigms/bc/legacy/bc_train.py`](../../../training/paradigms/bc/legacy/bc_train.py)
  — BC pretrain 入口(原 AZ 栈+PPO 栈双份在 P5-E 后 dedupe)
