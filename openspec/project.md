---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
---

# GICG — Project Spec

> OpenSpec project-level spec。**新 session 从这里看 spec 视角**；开发协作
> 规则看 `AGENTS.md`；当前阶段状态看 `docs/0_status/README.md`。
>
> 本文件只描述 **稳定的项目立约**(architecture / invariants / paradigm
> landscape current state),不替代 ADR / runs registry / curriculum plan。

> 当前工作状态与接手顺序（2026-09-14）：[实时状态页](../docs/0_status/README.md) 与 [接手清单](../docs/HANDOFF.md)。
> [保留动态执行的设计路线](../docs/3_plans/dynamic_execution_to_training.md)仍为设计背景；具体活动任务以实时状态页为准。

## 1. Purpose

用户于2026-09-13明确当前两个核心目的：

1. 制作七圣召唤PvE决策辅助工具，为玩家提供每个决策的评分或经校准的成功率估计，帮助更快完成关卡。
2. 基于可靠环境、小模型规则表达与新内容适应的可验证实验，争取形成研究论文。

产品只支持最新官方正式服，不维护过时玩法。单次实验保留固定来源快照用于可复现；这不构成历史版本产品支持。当前教学池训练属于方法与工程验证，不能替代真实PvE验收。

详细分阶段规划与研究假设见 [PvE决策辅助与研究路线](../docs/3_plans/pve_assistant_and_research.md)。原有RL / AZ / CFR / BC / DMC框架是实现与研究手段；早期“仅算法可学性验证”的定位由以上最新用户目标取代。

## 2. Tech Stack

| 层 | 语言 / Runtime | 关键依赖 |
|---|---|---|
| 游戏数据 DSL | Lua syntax subset(自研解释器,非 LuaJIT) | — |
| Engine | Go 1.21+ | 无第三方运行时依赖 |
| MCTS | Go(`gicg_mcts/`) | 直接 import `gicg_engine/` |
| Python binding | Python 3.11 / ctypes | `libgicg.dylib` c-shared |
| RL training | Python + PyTorch | `gicg_env`、`gymnasium`-compatible 接口 |
| 容器化 | Docker Compose | Docker Desktop VM(9 CPU / 18 GB) |
| 评测 | `tools/eval/eval_service` localhost TCP daemon | DSL cache 复用 |

构建产物路径:`gicg_env/libgicg.dylib`(macOS)/ Linux 对应 `.so`,由 `go build
-buildmode=c-shared` 出。

## 3. Architecture

三层分离,数据流单向向上:

```
data/*.lua           ← DSL (game rules, characters, cards)
    │
    ▼  (loaded by interp/, no cgo bridge)
gicg_engine/         ← Go executor (generic counter+hook model)
gicg_mcts/           ← Go MCTS / IS-MCTS / PUCT
    │
    ▼  (c-shared via cgo)
gicg_env/            ← Python ctypes wrapper + GicgEnv RL env
    │
    ▼
training/            ← framework / az / cfr / dmc / ppo (5 stacks)
tools/               ← runs (paradigm dispatch) / _meta/send_matchup / eval_service / cards/...
```

**Top-level trees**:

- `data/` — DSL game data(`characters/` `cards/` `system/` `pools/`)
- `gicg_engine/` — Go engine + interp + capi
- `gicg_mcts/` — Go MCTS(L3 tree + PUCT + backup)
- `gicg_env/` — Python ctypes binding + `GicgEnv` class
- `training/` — core + paradigm split: `core/`(算法无关)+ `paradigms/<name>/`
  (5 paradigm adapters: az / ppo / cfr / dmc / bc);paradigm 互不 import,均只 import core
  (ADR-0006 + `openspec/specs/training-architecture/`)
- `tools/` — ad-hoc / eval / cleansing 脚本
- `docs/` — 当前状态、决策、计划、运行说明与历史证据；现行能力规约统一在 `openspec/specs/`
- `openspec/` — 本 spec 系统:`specs/`(shipped contracts)+ `changes/`
  (in-flight proposals)+ `changes/archive/`(historical changes)
- `artifacts/` — 按实验系列 tag 分组的运行产物，gitignored

**Dependency direction**(单向,无环):
`training/` → `gicg_env/` → `gicg_engine`(via dylib);
`gicg_mcts/` → `gicg_engine/`(Go 直接 import);
`tools/` → both;
`openspec/` 只描述,不被 import。

## 4. Key Invariants

项目立约。违反这些立约的代码必须被拒。

### I1. Engine Ignorance(引擎无知)

- Go engine **只**知道:characters、hand、deck、round、turn。
- Go engine **不**知道:HP、energy、elements、shields、freeze、AP、reactions。
- 所有游戏机制 = counter + hook,在 DSL 表达。
- 引擎是 generic executor;不为任何游戏术语开 special-case 分支。

### I2. Data-Engine Separation(数据-引擎分离)

- 游戏规则在 Lua DSL(`data/`)。
- 引擎是 generic executor(Go,`gicg_engine/`)。
- Python 只做 DL training,**不**做规则。
- 想加新机制 → 改 DSL,不改 Go(除非 generic 能力缺失)。

### I3. Counter + Hook Model

- **Counter**:扁平 `[]Counter` 数组;Value / Init / Min / Max + auto-clamp。
- **Hook**:扁平 hook 数组,按 HookType 分发,Priority 高先(默认 0),同 priority
  按注册顺序。
- **Go 内无 filter matching**:DSL callback 自己 early-return on `ctx.*` 字段。
- **Skill ID 全局唯一自增**:`ctx.skill_index` 充分识别任何 skill。
- 完整 DSL 参考:[`openspec/specs/engine-dsl/`](specs/engine-dsl/spec.md)（subtopic: counter / hook / damage / skill-pattern / builtin-api / file-structure）。

### I4. Declare/Get 模式

- `create_counter` / `declare_skill` / `declare_card` 用 named declare-or-get,
  positional args。
- Buff 文件拥有自己所有 effects;base skill 文件保持 pure。

### I5. No IDs in Observation

- Agent observation 必须用 functional property,**绝不**用 ID。
- Shuffle 防止 position memorization。

### I6. DSL 表达力硬约束

- 不支持 closure return / 顶层 function / 顶层全局表赋值。
- DSL 只看 `*SkillRef` / `*CardRef`(typed),不暴露 int `.id`。
- Sentinel 值用 `-1`(CardRef 从 0 起)。

### I7. CWD Convention

- 所有命令从 repo root 跑。
- Python 用 `python -m <module>` 调用,不要 `python path/to/file.py`。
- 脚本内路径使用仓库根目录相对路径。

### I8. Artifacts Naming

- `artifacts/` 顶层目录是 `experiment_tag`；同一系列的 seed、重试和评估共享同一个 tag。
- 每个新式 run 目录为 `artifacts/<experiment_tag>/<YYYYMMDDHHMM>_<NNNNNN>/`；时间戳为 UTC，编号为六位十进制序号。
- `python -m tools.runs.train <cfg>` 原子完成编号分配、目录创建、配置快照、训练和 metadata 收尾。
- 每个目录自带 `metadata.toml`、`cfg_leaf.toml`、`cfg_resolved.toml`、`ckpts/`、`metrics.jsonl` 与可选 `tb/`；不存在并行的 live registry 文件。
- 查看用 `tools.runs.list/show`，外部死亡用 `tools.runs.mark`，metadata 丢失用 `tools.runs.recover`，跨机元数据同步用 `tools.runs.sync`。Pre-redesign r001-r012 与 s001-s068 见 `docs/5_history/runs_pre_redesign_2026_05_17.md`。

### I9. 反向工程禁区

- DSL 静态 topo 扫描下,char-skill 文件 **不能** `get_card("X")`(architectural
  constraint)。
- 反向引用走 `sharedFiles` 声明。

## 5. Paradigm Landscape(2026-05-15 historical snapshot)

以下表格保留 2026-05-15 当时的路线判断，不代表 2026-09-14 的活动实验状态。
当前目标、运行与下一决策只看 [`docs/0_status/README.md`](../docs/0_status/README.md)；
历史 verdict 与复现数据见 [`docs/paradigms/`](../docs/paradigms/) 和 `docs/5_history/`。

| Paradigm | 代码位置 | 当前状态 | 关键 ADR |
|---|---|---|---|
| PPO | `training/paradigms/ppo/` | **Closed** 2026-04-26 (Stage 3 F1-D2 plateau 物理不可达) | 0008 / 0009 |
| AZ pure self-play | `training/paradigms/az/` | **Closed** 2026-04-28(s069 cancelled,mirror Nash 锁死) | 0009 / 0010 |
| AZ + BC warm-start | 当时的 BC 预训练产物 + AZ adapter | r010 × 3 seed mean = +0.06 vs baseline,仍 < stricter_pass | 0008 / 0009 |
| CFR(Deep CFR) | `training/paradigms/cfr/` | **Closed** r008 collapse(iter 199 < iter 20) | 0008 |
| BC alone | 当时的 BC 预训练入口与产物 | **Production maintenance**(r009 ≈ 0.75 vs F1-D2);RL 研究意义有限 | 0008 |
| DMC(Deep Monte-Carlo) | `training/paradigms/dmc/` | **当时 Active**，Phase 3.5 infra 刚完成 | — |

新 RL 任务先读实时状态与历史 dossier，避免把旧路线结论误当成当前运行状态。

## 6. Conventions Reference

本 spec 不重复以下文档已写的内容。优先级从高到低:

| 关注点 | 文档 | 备注 |
|---|---|---|
| 开发流程 / 工具调用 / 提交检查 | [`/AGENTS.md`](../AGENTS.md) | 项目特定；每个 agent 会话注入 |
| 跨项目协作风格 / 提交纪律 / 测试纪律 | 当前客户端注入的用户级指引 | 不属于仓库内容；不得作为项目事实引用 |
| OpenSpec 文件约定 / 行数限制 / 命名 | `openspec/specs/openspec-policy/`(P0-T3) | 本 migration P0-T3 落盘 |
| DSL 完整 API / counter 语义 / damage pipeline | [`openspec/specs/engine-dsl/`](specs/engine-dsl/spec.md) | DSL author 必读 |
| Engine 内部 / capi / search | `openspec/specs/engine-capi/` `openspec/specs/search-ismcts/` `openspec/specs/search-parallel/` | 实现细节 |
| Env 接口 / obs schema | `openspec/specs/env-config/` | RL 集成必读 |
| 决策日志 ADR | `docs/2_decisions/adr-NNNN-*.md` | 历史决策可追溯 |
| 当前 phase / 下一步 | `docs/0_status/README.md` | LIVE,事件发生同 commit 更新 |
| Run lifecycle (live) | `tools.runs.{train,list,show,mark,recover,sync}` CLI | 每个 `artifacts/<experiment_tag>/<ts>_<NNNNNN>/metadata.toml` 自包含；`train` 原子创建并收尾 |
| Run registry (pre-redesign archive) | `docs/5_history/runs_pre_redesign_2026_05_17.md` | r001-r012 + s001-s068 frozen snapshot |

历史 changes / ADR-to-OpenSpec 迁移:见 `openspec/changes/archive/`。

## 7. OpenSpec 使用边界

本目录(`openspec/`)管什么 / 不管什么:

**管**:
- 稳定项目立约(本文件 `project.md`)
- Shipped feature contract(`openspec/specs/<capability>/spec.md`)
- In-flight 变更提议(`openspec/changes/<name>/{proposal,design,tasks,delta}.md`)
- 历史归档(`openspec/changes/archive/`)

**不管**:
- 当前 phase / WIP 状态 → `docs/0_status/`
- ADR(历史决策叙述)→ `docs/2_decisions/`(P1 选择性迁移到 archive)
- Run 注册表 / 实验数据 → `docs/4_runs/`、`artifacts/`
- 开发流程 / 提交 / hook → `AGENTS.md`
- LLM 私有上下文可以辅助工作，但不是项目事实来源。任何影响接手、实现、
  运行或验收的事实必须写入本仓库的 spec、状态页、历史报告或代码注释。

**Slash commands**(本 repo 跟版):
- `/opsx:propose` — 新提议(`.claude/commands/opsx/propose.md`)
- `/opsx:apply` — 实施任务
- `/opsx:explore` — 思考分区
- `/opsx:archive` — 归档完成的 change

对应 skills 在 `.claude/skills/openspec-{propose,apply-change,explore,
archive-change}/SKILL.md`,通过 `.gitignore` 白名单跟 repo 走。
