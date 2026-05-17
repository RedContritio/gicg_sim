# 2_decisions/ — ADR (Architecture Decision Records)

> 纯**决策**日志。每份 ADR 记录"在 X 处选了 Y,因为 Z"。
>
> 区别:
> - `1_specs/` 写"现在长什么样" — ADR 写"为什么这样"
> - `3_plans/` 写"打算做什么" — ADR 写"已经决定的"
> - `5_history/` 写"出过什么事" — ADR 决定本身不入 history,只有"已被取代的 ADR"才标 superseded

## 命名

`adr-NNNN-slug.md`,NNNN 按时间序大致递增,slug 短描述。新 ADR 模板见 [`_template.md`](_template.md)。

## 时间序索引

| ID | 决策 | 日期 | 主题 | 状态 |
|---|---|---|---|---|
| [0001](adr-0001-web_live_mcts_cancel.md) | Web live MCTS 中断机制 | 2026-04 | web/eval | active |
| [0002](adr-0002-capi_obs_d5_d9.md) | C API & 观测空间 (D5-D9) | 2026-04-13 | engine/env | active |
| [0003](adr-0003-engine_bugs_d10_d13.md) | 引擎 bug 修复 (D10-D13) | 2026-04-13 | engine | active |
| [0004](adr-0004-is_mcts_migration.md) | PPO → AZ + IS-MCTS 迁移 | 2026-04-14 | paradigm | active |
| [0005](adr-0005-az_decisions_d1_d14.md) | AZ 14 项顶层决策包 (D1-D14) | 2026-04-14 起 | network/search/training | active (D14 ExpandUnionK 废弃 2026-04-21 在文内标注) |
| [0006](adr-0006-training_layout.md) | training/ 三层拆分 (framework/az/cfr) | 2026-04-23 | training | active |
| [0007](adr-0007-ppo_bc_warmstart.md) | PPO Stage 0/1 BC warm-start | 2026-04-25 | training/ppo | active |
| [0008](adr-0008-rl_paradigm_pivot.md) | RL paradigm 转向 (pure E2E → curriculum + BC + dense reward) | 2026-04-24 | paradigm | active |

## 主题索引

### 元方法 (paradigm / curriculum)
- [adr-0004](adr-0004-is_mcts_migration.md) — PPO → AZ 迁移
- [adr-0008](adr-0008-rl_paradigm_pivot.md) — pure E2E → curriculum + 混合架构

### 网络与搜索 (AZ)
- [adr-0005](adr-0005-az_decisions_d1_d14.md) — AZ D1-D14 包 (含 IS-MCTS / struct_readout / dice / 反 ID)

### 训练管线
- [adr-0006](adr-0006-training_layout.md) — framework/az/cfr 三层
- [adr-0007](adr-0007-ppo_bc_warmstart.md) — PPO Stage 0/1 BC warm-start

### 引擎与 capi
- [adr-0002](adr-0002-capi_obs_d5_d9.md) — capi 与 obs (D5-D9)
- [adr-0003](adr-0003-engine_bugs_d10_d13.md) — 引擎 bug 修复 (D10-D13)

### Web / Eval
- [adr-0001](adr-0001-web_live_mcts_cancel.md) — Web live MCTS 中断

## 状态枚举

- **active**: 当前生效
- **superseded by adr-NNNN**: 被新 ADR 取代
- **partially superseded**: 部分条款被取代
- **withdrawn**: 撤回 (rare)

## 早期 D1-D4 说明

D1-D4 (DSL API: get_next_char / draw_card_self / force_switch_next / 死代码清理) 是项目早期 DSL API 调整,
作为档案保留在 [`../5_history/decisions_legacy/dsl_api_d1_d4.md`](../5_history/decisions_legacy/dsl_api_d1_d4.md)。
未来 DSL API 变更走新 ADR。

## 编辑规则

- ADR 一旦 commit,**正文不再改**(事实纠错除外,加 `> 更正 (日期):`)
- 状态变更通过新 ADR + 修原 ADR frontmatter `status` 字段
- 不删 ADR(即使 withdrawn)
