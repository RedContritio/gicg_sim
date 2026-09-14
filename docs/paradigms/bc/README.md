---
last_updated: 2026-05-16
status: HISTORICAL
schema_version: 0
paradigm: bc
---

# BC paradigm dossier

> 2026-05-16 snapshot；当前训练状态见 [`../../0_status/README.md`](../../0_status/README.md)。

> **Status**: **PRODUCTION FALLBACK**(ADR-0009 钦定)
>
> **One-line verdict**: r009 BC ckpt epoch_3 vs F1-D2 = **0.75**(BC argmax 超 teacher
> 自身因 tied-noise reduction);PPO/AZ Stage 3 ceiling 0.34/0.27 之外的最强可
> 部署 agent。**production maintenance OK,RL 研究意义有限**(per memory
> `project_bc_alone_evaluation`):F1-D2 ceiling at Stage 3,zero-shot 跨角色/卡池 NOT 学得到。

## Overview

BC(Behavior Cloning)在 GICG 是 paradigm pivot 的核心 enabler:

1. **Stage 1/2 BC pretrain**(s016-s019,2026-04-25):d=1024 / h=4 / 60 epoch /
   soft target → soft_match 73% / 66%(Stage 1 / 2)。
2. **BC warm-start for PPO Stage 1/2 PASS**(s017 / s020):BC→PPO F1-D2 = 0.500 / 0.531
   PASS;**+0.24 dominant lever**(详 [`../ppo/ablations.md`](../ppo/ablations.md))。
3. **Stage 3 BC pretrain**(r009 / s022):d=1024 / h=4 / 60ep / 50k decisions /
   F1-D2 teacher;epoch_3 选作生产 ckpt,vs F1-D2 = **0.75**(配合 pairwise probe)。
4. **Stage 3 BC warm-start for AZ FAIL**(r010,2026-04-28):BC ckpt 0.75 → AZ
   training F1-D2 = 0.167,**self-play distribution shift 摧毁 BC 策略**。
5. **ADR-0009 钦定 production fallback**:BC ckpt 单独部署是最强 viable agent;
   PPO/AZ 不能 robustly 超越。

## Why BC argmax 超 teacher

F1-D2 greedy teacher 自身受 **tied-decision random tiebreak** 噪声影响(tied_mask
mean 2.83 per decision)。BC soft target distillation 在 ties 上学到加权平均策略,
argmax 选 soft-target 最大概率 action,等效于 majority-vote tiebreak,**降低噪声**。

定量:F1-D2 vs F1-D2 control = 0.54(对称小偏差),BC ckpt vs F1-D2 = 0.75 — 这 0.21
gap 主要来自 tied-noise reduction,非 BC "学到更深策略"。详 memory `project_bc_warmstart_progress`。

## Verdict tree

```
BC pretrain capacity sweep (s016/s016b/s016d)
├── d=256/h=2/10ep → soft_match 34% FAIL
├── d=512/h=4/30ep → soft_match 66% MARGINAL
└── d=1024/h=4/60ep → soft_match 73% (Stage 1 ceiling near 80%)

BC + PPO Stage 1/2 (s017/s020)
├── Stage 1 F1-D2 = 0.500 PASS ✅
└── Stage 2 F1-D2 = 0.531 PASS ✅

BC + PPO Stage 3 (s022/s023-s054 ablation)
└── F1-D2 ceiling 0.344 ± 0.062 FAIL stricter ❌
    └── ADR-0009 closure → BC alone 作 production fallback

BC + AZ Stage 3 (r010)
└── F1-D2 = 0.167 ± 0.029 FAIL — AZ training destroys BC ❌

r009 BC ckpt epoch sweep (r009_bc_eval_ep0..6)
└── epoch_3 best vs F1-D2 = 0.75 → ship as production fallback
```

## Key data points

| Run | Cfg | Result |
|---|---|---|
| s015 | BC data gen Stage 1 50k F1-D2 teacher | hard ceiling 0.354 / tied_mask 2.83 |
| s016d | d=1024/h=4/60ep Stage 1 | soft_match 73% |
| s017 | BC + PPO Stage 1 | F1-D2 = 0.500 PASS ✅ |
| s019 | BC pretrain Stage 2 | soft_match 66% |
| s020 | BC + PPO Stage 2 | F1-D2 = 0.531 PASS ✅ |
| s022 | BC pretrain Stage 3 | soft_match 62.1% |
| s023-s054 | BC + PPO Stage 3 ablation × 29 | ceiling 0.344 ± 0.062 ❌ |
| **r009 BC epoch_3** | Stage 3 final ckpt | **vs F1-D2 = 0.75** ✅(production)|
| r010 | BC + AZ Stage 3(× 3 seed)| F1-D2 = 0.167 ± 0.029 ❌ |

## Subdirectories

- [Runs](./runs.md) — BC era run 时间序列
- [Postmortems](./postmortems.md) — r010 BC destruction + Stage 3 ceiling 复盘

(无 dedicated ablations.md — BC capacity sweep + Stage 3 4-factor ablation 与
PPO/AZ dossier 重叠,见 [`../ppo/ablations.md`](../ppo/ablations.md) +
[`../az/ablations.md`](../az/ablations.md);BC alone 的 architecture iteration 也无,
共享 PPO/AZ ActorCritic 网络)

## Cross-references

**Archived OpenSpec changes**:

- [`openspec/changes/archive/0007-ppo-bc-warmstart/`](../../../openspec/changes/archive/0007-ppo-bc-warmstart/)
  — BC warm-start 引入(Stage 1/2 PASS 触发)
- [`openspec/changes/archive/0009-rl-paradigm-pivot-terminus/`](../../../openspec/changes/archive/0009-rl-paradigm-pivot-terminus/)
  — 钦定 BC ckpt 作 production fallback(Stage 3 ceiling closure 时)

**Frozen history**:

- [`docs/5_history/r010_az_bc_warmstart_postmortem.md`](../../5_history/r010_az_bc_warmstart_postmortem.md)
  — r010 BC + AZ destruction 完整诊断(canonical)
- [`docs/5_history/az_plans/r009_az_warmstart.md`](../../5_history/az_plans/r009_az_warmstart.md)
  — r009 BC pretrain plan(archived,含 epoch sweep design)
- [`docs/5_history/ablations/stage3_ppo_closure.md`](../../5_history/ablations/stage3_ppo_closure.md)
  — Stage 3 4-factor ablation 含 BC factor 量化

**Run registry**:
[`docs/5_history/runs_pre_redesign_2026_05_17.md`](../../5_history/runs_pre_redesign_2026_05_17.md):

- s015-s020(Stage 1/2 BC + PPO PASS)
- s021-s054(Stage 3 BC + PPO ablation)
- r009 BC pretrain + epoch sweep(configs/r009_bc_eval_ep[0-6].toml,刚 commit `1f180bd`)
- r010(BC + AZ Stage 3 multi-seed)

**Memory**:

- `project_bc_warmstart_progress` — BC warm-start 提升路径 + tied-noise reduction 解释
- `project_bc_alone_evaluation` — BC alone production OK / RL 研究意义有限
- `project_v_phase2_eval_schema_gaps` — ADR-0011 schema 落地遗漏(BC eval 配套)

**Code**:

- 历史 `training/paradigms/bc/legacy/bc_train.py` 已退役；当前 BC 通过统一
  `tools.runs.train` lifecycle 运行
- [`training/paradigms/bc/`](../../../training/paradigms/bc/) — BC first-class adapter
  (P4-T2 ship,paradigm.py + collector.py + policy.py + loss.py + network.py)
- [`tools/dataset/gen_bc.py`](../../../tools/dataset/gen_bc.py) — BC dataset 生成
- [`configs/_archived/bc_apr/r009_bc_pretrain_stage3.toml`](../../../configs/_archived/bc_apr/r009_bc_pretrain_stage3.toml) — r009 BC pretrain 历史 cfg
- [`configs/_archived/bc_apr/`](../../../configs/_archived/bc_apr/) — r009 BC epoch eval 历史 cfg
