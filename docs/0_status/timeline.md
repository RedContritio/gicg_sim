---
last_updated: 2026-09-14
status: HISTORICAL — covers events through 2026-05-16
---

# Timeline — 项目重大事件线

> 时间序记录关键里程碑、决策点、failure / pivot。每条一行,date + 一句话 + ADR/postmortem 链接。
>
> **不是 git log。** 只记影响"为什么走到这"的事件,不记纯代码 commit。
> 本页目前只覆盖到 2026-05-16；最新状态见 [README](README.md)，
> 后续实验见 [`docs/5_history/`](../5_history/)。

## 2026-05

| Date | Event | 链接 |
|---|---|---|
| 2026-05-15/16 | **OpenSpec 全量迁移**(P0+P1):17 commits / scaffold + 11 capability spec + 15 ADR archive + 5 paradigm dossier + 7 plan archive | [paradigms/README](../paradigms/README.md) / [openspec/project](../../openspec/project.md) |
| 2026-05-15 | v_phase2 卡 e2e tests ship: 事件/支援/装备 7 case 真路径 + cleaned yaml ground truth | [v_phase2_cards_e2e_impl(archived)](../5_history/v_phase2_cards_e2e_impl.md) |
| 2026-05-15 | support zone lifecycle ship: SlotSupport state + 6 hooks + 6 区生命周期 spike | [support_lifecycle_impl(archived)](../5_history/support_lifecycle_impl.md) |
| 2026-05-15 | DMC Phase 3.5 infra refactor 全 done: tools/eval+remote paradigm-agnostic / NaN guard / single+mp 合并 entry | [dmc_phase35_infra(archived)](../5_history/dmc_phase35_infra.md) |
| 2026-05-14 | DMC review 41 项 critique 落盘 | [reviews/dmc_review](../5_history/reviews/dmc_review.md) |
| 2026-05-13/14 | DMC Phase 3.4 smoke verified(5035 frame / 136 ep / loss 0.95→0.67),Phase 3.5 multi-process actor-learner ship | [dmc/notes](../../training/paradigms/dmc/notes.md) |
| 2026-05-12 | v_phase2 真实角色 / 卡牌池建立(7 char / 6 卡)+ RL smoke 跑通(s070)+ ADR-0011 schema fix | [archive s070](../5_history/runs_pre_redesign_2026_05_17.md) |
| 2026-05-04 ~ 05-07 | **ADR-0019 DSL v6 strict 落地**(23 commits,strict 8 hook 流水线 + Phase 2 真路径,§A.3 Phase 2 完整 fidelity 保留)| [archive/0019-dsl-v6-semantic-engine](../../openspec/changes/archive/0019-dsl-v6-semantic-engine/) |

## 2026-04

| Date | Event | 链接 |
|---|---|---|
| 2026-04-26 | Stage 3 BC→PPO closure: 29 ablation 证 F1-D2 ≥ 0.40 stricter 不可达,pivot AZ 路线 | [stage3_ppo_closure](../5_history/ablations/stage3_ppo_closure.md) |
| 2026-04-25 | Stage 1+2 BC→PPO PASS (s017/s020),multi-seed infra 落地 | [stage1](../5_history/curriculum/stage1.md) |
| 2026-04-24 | **RL paradigm pivot**: pure end-to-end (r001-r008) 全失败,转 curriculum + BC warm-start | [ADR-0008](../2_decisions/adr-0008-rl_paradigm_pivot.md) |
| 2026-04-24 | RL Curriculum 5-stage 计划锁定 | [curriculum/plan](../5_history/curriculum/plan.md) |
| 2026-04-23 | r008 (Deep CFR 200 iter) 失败 postmortem | [CFR postmortems](../paradigms/cfr/postmortems.md) |
| 2026-04-21 | ExpandUnionK 废弃 (D14): K=3 净负 0.05,只覆盖 dice 维 <20% D1 触发场景 | [ADR-0005](../2_decisions/adr-0005-az_decisions_d1_d14.md) |
| 2026-04-19 | AZ C1v7 random_1v1 random_team 通过 (vs mcts_200=0.45/0.55) | [c1v7_success memory] |
| 2026-04-18 | C1v7 struct_readout 突破 cross-attn pool 零空间问题 | [ADR-0005](../2_decisions/adr-0005-az_decisions_d1_d14.md) |
| 2026-04-17 | hook_encoder 梯度断流 bug 发现 — C1-F 系列 ckpt 全作废 | [c1_postmortem](../5_history/postmortems/) |
| 2026-04-15 | PPO 时代决策连同 PPO 训练栈归档 (r001 之前的老 PPO,非 Stage curriculum 的 PPO) | [eras/ppo_pre_az](../5_history/eras/) |
| 2026-04-14 | **PPO → AZ 迁移决策**: phase1b plateau + MCTS 117-3 击败训练策略 | [ADR-0004](../2_decisions/adr-0004-is_mcts_migration.md) |

## 命名说明

- **r001-r008**: AZ/CFR 时代第一批 production-style training run,paradigm pivot 前
- **C1/C1v1-v7**: AZ 网络架构迭代 (C1v7 是首次反 ID 公平验证通过)
- **Stage 0-5**: RL Curriculum 阶段 (paradigm pivot 后的主线)
- **s001-s054**: smoke / validation run (含 PPO Stage 0-3 全部实验)
- **PPO pre-AZ**: r001 之前的旧 PPO 时代 (phase{0-5} 课程,2026-04-14 前)
- **PPO Stage curriculum**: paradigm pivot 后的新 PPO (Stage 0-3),用 BC warm-start
