# docs/

> **新 session 第一站读 [`0_status/README.md`](0_status/README.md)**。30 秒回答"现在做什么 / 上里程碑 / 下决策点"。

```
docs/
├── 0_status/    LIVE 入口 — 现在在哪
├── 2_decisions/ ADR (adr-NNNN-*.md, 时间序 + 主题序双索引)
├── 3_plans/     LIVE 计划与 roadmap (backlog / cards / v_phase2_deferred)
├── 4_runs/      Run lifecycle 入口 + pre-redesign 单 run 资料
├── 5_history/   冻结 (postmortems / reviews / audits / evidence / ablations / decisions_legacy / eras)
└── paradigms/   2026-05 paradigm dossier 历史快照
```

现行能力规约统一位于 [`../openspec/specs/`](../openspec/specs/)；`docs/` 保存实时状态、计划、决策和历史证据。

## 想知道什么 → 读哪

| 想知道 | 读哪 |
|---|---|
| **当前任务 / 上里程碑 / 下决策点** | [`0_status/README.md`](0_status/README.md) |
| 时间序大事件 | [`0_status/timeline.md`](0_status/timeline.md) |
| 术语速查 (Stage / r/s / lever / scenario) | [`0_status/glossary.md`](0_status/glossary.md) |
| 当前网络架构 | [`../openspec/specs/network-architecture/`](../openspec/specs/network-architecture/) |
| 当前 DSL API | [`../openspec/specs/engine-dsl/`](../openspec/specs/engine-dsl/) |
| 当前 IS-MCTS 算法 | [`../openspec/specs/search-ismcts/`](../openspec/specs/search-ismcts/) |
| 为什么选 AlphaZero / IS-MCTS | [`2_decisions/adr-0004-is_mcts_migration.md`](2_decisions/adr-0004-is_mcts_migration.md) |
| 为什么 paradigm pivot | [`2_decisions/adr-0008-rl_paradigm_pivot.md`](2_decisions/adr-0008-rl_paradigm_pivot.md) |
| Stage 状态(已归档) | [`5_history/curriculum/`](5_history/curriculum/) |
| 跨项目待办 | [`3_plans/backlog.md`](3_plans/backlog.md) |
| 某次 run 配置 / 结果(live) | `python -m tools.runs.show <run_id>` CLI |
| 某次 run 配置 / 结果(pre-redesign 2026-05-17 之前) | [`5_history/runs_pre_redesign_2026_05_17.md`](5_history/runs_pre_redesign_2026_05_17.md) |
| 某次 run 为什么崩了 | [`5_history/postmortems/`](5_history/postmortems/) |
| 某次 ablation 数据 | [`5_history/ablations/`](5_history/ablations/) |
| PPO pre-AZ era 归档 | [`5_history/eras/ppo_pre_az/`](5_history/eras/ppo_pre_az/) |

## 编辑规则

每个子目录有自己的 README 详述其编辑规则。简版:

| 目录 | LIVE? | 编辑频率 |
|---|---|---|
| `0_status/` | ✅ | 事件触发 (每 phase 切换 / 里程碑) |
| `2_decisions/` | 追加式 | 新决策 = 新 ADR,旧 ADR 不改正文 |
| `3_plans/` | ✅ | 计划演进随 commit |
| `4_runs/` | 入口说明 | 新 run 由 `tools.runs.train` 与每个 artifacts 目录的 metadata 管理 |
| `5_history/` | 冻结 | 不再编辑;事实纠错加 `> 更正 (日期):` |

## 路径规范

- 跨子目录引用用相对路径 `../../2_decisions/adr-NNNN-*.md`
- ADR 编号一旦发出不变 (stable identifier)
- mv 后 link 由 docs 大改 commit 一并修

## 历史

2026-04-26 曾重组为 `0_status/ + 1_specs/ + 2_decisions/ + 3_plans/ + 4_runs/ + 5_history/`；
随后 shipped specs 迁入 `openspec/specs/`，`1_specs/` 已移除。2026-05-18 起 run metadata 改为每个 artifacts 目录自包含。
