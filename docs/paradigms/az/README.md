---
last_updated: 2026-05-16
status: LIVE
schema_version: 0
paradigm: az
---

# AZ paradigm dossier

> **Status**: **CLOSED**(主线 by ADR-0009)/ **PARTIAL REOPEN**(by ADR-0010,2026-04-28)
>
> **One-line verdict**: AZ Stage 0-2 PASS;Stage 3 1-card plateau 0.10-0.27 across stacks;
> s068 D4 asymmetric mirror-break +0.167 部分推翻 closure 强命题,触发 ADR-0010 reopen;
> s069 cancelled(per memory `project_rl_routes_closure_2026_05_12` user 决策)。

## Overview

AZ 是 2026-04-26 ~ 04-28 期 GICG RL 路线,paradigm pivot 自 PPO closure 后启动。
核心轨迹:

1. **架构演化 C1v0-v7**(2026-04-09 ~ 04-18):ID-leak → cross-attn 饱和 →
   struct_readout 引入 → 反 ID 公平验证 PASS(argmax vs mcts_200 = 0.45)。
   详 [`architecture.md`](./architecture.md)。
2. **Stage 0-2 baseline**(s055-s063,2026-04-26):Stage 0/1/2 全 PASS vs random,
   mcts_200 wr 0.31-0.69 跨 seed。
3. **Stage 3 1-card plateau**(s064-s066,2026-04-26):AZ pure self-play F1-D2
   = 0.104 ± 0.072,远低 PPO BC 0.344。BC warm-start(r010,2026-04-28)
   也只到 0.167 ± 0.029 — 不传递 PPO 的 dominant lever。
4. **D4 asymmetric mirror-break**(s068,2026-04-28):pure self-play asymmetric
   teams F1-D2 = 0.271 ± 0.094(seed43 = 0.375),+0.167 vs s064-66 mirror baseline。
   部分推翻 closure 强命题 → ADR-0010 reopen。
5. **s069 cancelled**:more_rollouts probe,user 决策不继续(per memory
   `project_rl_routes_closure_2026_05_12`,DMC 路线作为新主线)。

## Verdict tree

```
AZ Stage 0 (mirror + fix_dice)
├── s055/s056/s057 n=3 seed
└── mcts_200 wr = 0.69/0.56/0.38 → vs random PASS

AZ Stage 1 (stochastic dice)
├── s058/s059/s060 → mcts_200 = 0.31/0.50/0.31
└── F1-D2 ladder backfill 显示弱(F1-D2 等同 stage 0-1)

AZ Stage 2 (partial obs)
├── s061/s062/s063 → mcts_200 0.31-0.50
└── F1-D2 ≤ 0.25 全 seed

AZ Stage 3 (card_pool)
├── 1-card masked baseline (s064-s066) → F1-D2 = 0.104 ± 0.072 ❌
├── BC warm-start (r010 × 3 seed) → F1-D2 = 0.167 ± 0.029 ❌(远低 PPO 0.344)
├── multi-card baseline (s067 × 3) → F1-D2 = 0.062 ± 0.062 ❌
├── D4 asymmetric mirror-break (s068 × 3) → F1-D2 = 0.271 ± 0.094 (+0.167) ⚠
└── ADR-0010 PARTIAL REOPEN;s069 (more_rollouts probe) cancelled
```

## Key data points

| Milestone | Run | F1-D2 wr | Note |
|---|---|---|---|
| C1v7 first ship(pre-curriculum)| 202604180500_az_c1v7 | — | g400 mcts_200=0.45;sid pin + struct_readout 反 ID PASS |
| Stage 3 1-card baseline | s064/s065/s066 | 0.104 ± 0.072 | AZ pure self-play 在 Stage 3 真实 plateau |
| Stage 3 BC warm-start | r010 × 3 seed | **0.167 ± 0.029** | BC ckpt 是 0.75 vs F1-D2,AZ training destroys teacher signal |
| Stage 3 multi-card baseline | s067 × 3 seed | 0.062 ± 0.062 | 3-card pool plateau,与 PPO multi-card 0.10 一致 |
| **Stage 3 D4 asymmetric**(s068)| s068 × 3 seed | **0.271 ± 0.094** | partial reopen lever;mirror Nash 锁死 was 主因之一 |
| Stage 3 D4 more_rollouts probe | s069 × 3 seed | **cancelled** | per user 评估 closure 扩展 |

## Subdirectories

- [Runs](./runs.md) — s055-s069 + r010 multi_seed n=3 (seed42/43/44) time-ordered
- [Ablations](./ablations.md) — Stage 3 stack comparison + D4 probe
- [Architecture](./architecture.md) — C1v0-v7 演化 + 6 hook gradient bug 修复 link
- [Postmortems](./postmortems.md) — Stage 3 plateau / BC destruction / r010 复盘

## Cross-references

**Archived OpenSpec changes**:

- [`openspec/changes/archive/0004-is-mcts-migration/`](../../../openspec/changes/archive/0004-is-mcts-migration/)
  — IS-MCTS migration(AZ search engine)
- [`openspec/changes/archive/0005-az-decisions-d1-d14/`](../../../openspec/changes/archive/0005-az-decisions-d1-d14/)
  — AZ D1-D14 决策合订(parallel rollout / mcts profile / determinize 等)
- [`openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`](../../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/)
  — Curriculum closure 含 AZ Stage 3 数据
- [`openspec/changes/archive/0010-rl-research-reopen/`](../../../openspec/changes/archive/0010-rl-research-reopen/)
  — s068 D4 推翻强命题后 partial reopen 决策

**Frozen history**:

- [`docs/5_history/network_design_history.md`](../../5_history/network_design_history.md)
  — C1v0-v7 完整网络架构演化 + 6 hook gradient bug 修复
- [`docs/5_history/algorithm_sweep_2026_04_28.md`](../../5_history/algorithm_sweep_2026_04_28.md)
  — s067-s069 batch sweep doc
- [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)
  — r010 BC warm-start destruction 诊断
- [`docs/5_history/az_plans/r009_az_warmstart.md`](../../5_history/az_plans/r009_az_warmstart.md)
  — r009 BC pretrain plan(archived)
- [`docs/5_history/postmortems/c1_postmortem.md`](../../5_history/postmortems/c1_postmortem.md)
  — C1 family postmortem
- [`docs/5_history/postmortems/c1v6_plan.md`](../../5_history/postmortems/c1v6_plan.md)
  — C1v6 fix plan(hook gradient bug 修复)
- [`docs/5_history/search_history.md`](../../5_history/search_history.md)
  — IS-MCTS engine history
- [`docs/5_history/evidence/mcts_vs_policy.md`](../../5_history/evidence/mcts_vs_policy.md)
  — MCTS vs policy 对照证据

**Run registry**:
[`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md):

- r001-r006(C1v7 era 400g + obs ablation)
- s055-s069(AZ Stage 0-3 + D4 probe)
- r010 multi_seed n=3 / seed=42/43/44(BC warm-start AZ multi-seed,registry 用同一 r010 label × 3 seed)
- 202604180500_az_c1v7 + 202604181653_az_c3(pre-registry C1v7 first ships)

**Memory**:

- `project_c1_failure_diagnosis` — C1v1 net-as-leaf 根因
- `project_c1v2_results` — lambda=0 rollout 训练验证
- `project_c1v4_status` — C1v4 状态
- `project_c1v7_success` — C1v7 反 ID 首次公平验证 PASS
- `project_az_stage0_3_baselines` — Stage 0-3 baseline 汇总(OBSOLETE — 见 closure)
- `project_algorithm_sweep_2026_04_28` — sweep doc
- `project_rl_closure_2026_04_28` — 上午 closure 决策(部分被 s068 推翻)
- `project_rl_routes_closure_2026_05_12` — 用户扩展 closure 集合(含 s069 cancel)
- `project_mcts_profile_design` — MCTS profile 数据结构
- `feedback_stale_weights_ok` — AZ async 训练 stale weight 容忍

**Code**:

- [`training/paradigms/az/`](../../../training/paradigms/az/) — AZ adapter
  (self-contained,2026-05-16 az-paradigm-rewrite Phase 5 完成 legacy retire):
  paradigm.py + collector.py + policy.py + loss.py + network.py + config.py +
  config_loader.py + buffer.py + selfplay.py + mcts/ + mcts_go.py +
  mcts_go_bindings.py + determinize.py + arena.py + inference_pool.py +
  inference_worker.py + train_step.py + train_az.py + train_loop/ +
  pool_spec.py。原 `legacy/` 子目录已 git rm,详
  [`openspec/changes/az-paradigm-rewrite/`](../../../openspec/changes/az-paradigm-rewrite/)
  (Phase 6 后 archive)。
- [`training/paradigms/bc/legacy/bc_train.py`](../../../training/paradigms/bc/legacy/bc_train.py)
  — BC pretrain 入口(P5-E 后从 AZ/PPO 双份 dedupe;BC first-class adapter 在
  [`training/paradigms/bc/`](../../../training/paradigms/bc/))
- [`gicg_mcts/`](../../../gicg_mcts/) — Go MCTS L3(tree + PUCT + backup)

**Retire status**:AZ legacy subdir(2026-04 原结构)已于 2026-05-16
完成 git rm,adapter 已自包含;legacy 12 个文件 + 1 个 r009 parity test
(`test_az_network_phase2_r009_smoke.py`)已删除;Phase 1 gate 34/34 +
Phase 2/3/4 path tests 全 pass。
