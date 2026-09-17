# 3_plans/ — 计划与 roadmap

> "**打算做什么**" 的 LIVE 文档。区别:`2_decisions/` 写"已经决定的"。
>
> LIVE plan 跑完一次 closure 后,**整 plan 移到** `5_history/`(顶部加 ARCHIVED note)
> 并留指针到产出(artifact / commit / postmortem)。主 plan 改动走新 commit 描述差异。
> 命名:`<topic>.md` 单文件;`<topic>/plan.md` + 子文件为多文件 plan。
>
> 本目录中自标 HISTORICAL 的文件不再更新，但留在原地：`dsl_gaps.md`、`cleansing_schema.md`、
> `effect_pattern_frequency.md`、`arch_unification_remaining_2026_05_16.md` 等被
> `openspec/`、`docs/2_decisions/` 与 `gicg_engine/` 源码注释引用，移动会破坏链接或源码指纹。

## 文件索引

| 文件 | 内容 | 状态 |
|---|---|---|
| [`rule_learning_roadmap.md`](rule_learning_roadmap.md) | 周/月级主路线:规则响应→稳定 D2 收益→原生新内容→PvE;目标、验收关口、备选方案与预算 | LIVE 主路线 |
| [`dynamic_execution_to_training.md`](dynamic_execution_to_training.md) | 主路线的动态执行实施细节与关口;当前排期以主路线图为准 | ACTIVE |
| [`pve_assistant_and_research.md`](pve_assistant_and_research.md) | 项目两个核心目的:最新正式服的 PvE 决策辅助 + 论文路线 | LIVE |
| [`pure_rl_long_term.md`](pure_rl_long_term.md) | 长期方向:全池基准完成后研究从零开始的纯 RL | LIVE |
| [`backlog.md`](backlog.md) | 跨项目待办;优先级在表格内标注,不按时间排序 | LIVE |
| [`versioning.md`](versioning.md) | 项目版本 vA.B.C 规则与历史映射 | LIVE |
| [`cards/native_content_curriculum.md`](cards/native_content_curriculum.md) | 从教学池迁移到审核完整的原生内容与 3v3;每批 1–2 角色 + 配套牌 | LIVE |
| [`cards/full_pool_curriculum.md`](cards/full_pool_curriculum.md) | 当前教学池 L1–L6 课程的目标、环境定义与验收协议 | LIVE |
| [`cards/policy_retention.md`](cards/policy_retention.md) | 配对规则训练后的六臂策略保留对照:固定数据/预算/seed，区分规则学习和策略退化 | DONE 2026-09-16 |
| [`cards/in_game_rule_verification.md`](cards/in_game_rule_verification.md) | 规则边界统一核验表:复现场景、当前处理、用户实测结果 | LIVE |
| [`cards/card_value_evaluation.md`](cards/card_value_evaluation.md) | 逐卡价值:胜率贡献与出牌时机的量化方案 | LIVE 方案 |
| [`cards/card_difficulty_grades.md`](cards/card_difficulty_grades.md) | 卡牌难度分级 L1–L6(curriculum 输入) | LIVE 参考 |
| [`inference_consistency_repairs.md`](inference_consistency_repairs.md) | 2026-09-14 推理一致性三项修复与集成验收 | 已完成 |
| [`commit_readiness_20260912.md`](commit_readiness_20260912.md) | 2026-09-12 提交整理快照 | 历史 |
| [`arch_unification_remaining_2026_05_16.md`](arch_unification_remaining_2026_05_16.md) | 2026-05-16 架构统一剩余项计划 | 历史 |
| [`v_phase2_deferred.md`](v_phase2_deferred.md) | 2026-05 `v_phase2` deferred backlog | 历史 |
| [`cards/cleansing_schema.md`](cards/cleansing_schema.md) | 卡牌清洗 schema 决策 | 历史 |
| [`cards/dsl_capabilities_audit.md`](cards/dsl_capabilities_audit.md) | 全 706 张牌的 DSL 能力审计 | 历史 |
| [`cards/dsl_gaps.md`](cards/dsl_gaps.md) | 全 706 张牌的 DSL 缺口清单 | 历史 |
| [`cards/spike_review.md`](cards/spike_review.md) | ADR-0012 spike 复盘 | 历史 |
| [`cards/effect_pattern_frequency.md`](cards/effect_pattern_frequency.md) | 2026-04 cleansed 语料的 pattern 频次统计 | 历史快照 |

## 已归档的 plans

下列 plans 已迁移到 [`../5_history/`](../5_history/):

| 原路径 | 归档位置 | 状态 |
|---|---|---|
| `curriculum/` | [`../5_history/curriculum/`](../5_history/curriculum/) | CLOSED per ADR-0009/0010 |
| `algorithm_sweep_2026_04_28.md` | [`../5_history/algorithm_sweep_2026_04_28.md`](../5_history/algorithm_sweep_2026_04_28.md) | STALLED → SUPERSEDED by DMC pivot |
| `acceptance.md` | [`../5_history/acceptance.md`](../5_history/acceptance.md) | OBSOLETE(phase 命名遗留) |
| `az/` | [`../5_history/az_plans/`](../5_history/az_plans/) | EXECUTED(r010-012 ship,F1-D2=0.167) |
| `support_lifecycle_impl.md` | [`../5_history/support_lifecycle_impl.md`](../5_history/support_lifecycle_impl.md) | IMPLEMENTED 2026-05-15 |
| `v_phase2_cards_e2e_impl.md` | [`../5_history/v_phase2_cards_e2e_impl.md`](../5_history/v_phase2_cards_e2e_impl.md) | IMPLEMENTED 2026-05-15 |
| `dmc_phase35_infra.md` + `dmc_phase35_infra_impl/` | [`../5_history/dmc_phase35_infra.md`](../5_history/dmc_phase35_infra.md) + [`../5_history/dmc_phase35_infra_impl/`](../5_history/dmc_phase35_infra_impl/) | IMPLEMENTED 2026-05-15 |
| `archived_tools_audit.md` | [`../5_history/audits/archived_tools_audit.md`](../5_history/audits/archived_tools_audit.md) | EXECUTED 2026-05-16(FU-W2.5d batch removal — Dead+Doc-only 11 files removed via `ade04ea`) |
| `cards/{consequence_policy_rl, paired_joint_rl, paired_consequence_training, rule_auxiliary_training, native_first_batch_audit}.md` | [`../5_history/cards/`](../5_history/cards/) | EXECUTED / AUDITED(2026-09-15 归档;LIVE 路线见 `cards/native_content_curriculum.md`) |
