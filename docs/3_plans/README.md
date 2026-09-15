# 3_plans/ — 计划与 roadmap

> "**打算做什么**" 的 LIVE 文档。
>
> 区别:
> - `2_decisions/` 写"已经决定的" — plans 写"准备做的"
> - 计划失败/废弃后,文档**不删**,移到 `5_history/` 并加 `ARCHIVED` 标头

## 子目录 / 文件

| 路径 | 内容 |
|---|---|
| [`rule_learning_roadmap.md`](rule_learning_roadmap.md) | 当前周/月级主路线：规则响应→稳定D2收益→原生新内容→PvE；目标、验收关口、备选方案与预算 |
| [`dynamic_execution_to_training.md`](dynamic_execution_to_training.md) | 动态执行到训练的实施细节；当前排期与关口以主路线图为准 |
| [`commit_readiness_20260912.md`](commit_readiness_20260912.md) | 2026-09-12 提交整理记录（历史工作区快照） |
| [`versioning.md`](versioning.md) | 项目版本 vA.B.C 规则与历史映射 |
| [`backlog.md`](backlog.md) | 跨项目待办 + 监控节奏约定 |
| [`cards/`](cards/) | 卡设计与难度分级资料(curriculum 输入) |
| [`cards/in_game_rule_verification.md`](cards/in_game_rule_verification.md) | 规则边界统一核验表：复现场景、当前处理、用户实测结果 |
| [`v_phase2_deferred.md`](v_phase2_deferred.md) | 2026-05 `v_phase2` deferred 历史 backlog；当前原生内容入口见 `cards/native_content_curriculum.md` |

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
| `cards/{consequence_policy_rl, paired_joint_rl, paired_consequence_training, rule_auxiliary_training, native_first_batch_audit}.md` | [`../5_history/cards/`](../5_history/cards/) | EXECUTED / AUDITED(2026-09-15 归档；LIVE 路线见 `cards/native_content_curriculum.md`) |

## 命名

- `<topic>.md` — 单文件 plan
- `<topic>/plan.md` + `<topic>/<sub>.md` — 多文件 plan(主规范 + 子计划)

## 编辑规则

- LIVE plan 跑完一次 closure 写入,**整 plan 沉淀到** `5_history/`(顶部加 ARCHIVED note)
- 主 plan 改了用新 commit + commit message 描述差异
- 完成的计划归档时,留指针到产出(artifact / commit / postmortem)

- [从零开始的纯强化学习长期方向](pure_rl_long_term.md)：用户2026-09-13确认，当前全池基准完成后研究。

- [原生角色与卡牌分批接入](cards/native_content_curriculum.md)：从教学池迁移到审核完整的原生内容和3v3，每批1–2角色与配套牌。

- [PvE决策辅助与论文路线](pve_assistant_and_research.md)：最新用户目标，只支持最新正式服，逐动作建议、估值校准与新内容适应研究。
