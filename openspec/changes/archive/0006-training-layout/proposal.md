# Training layout — three-layer split (framework / az / cfr)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0006-training_layout.md` at P1-T1)
**Original date:** 2026-04-23
**Original status:** Accepted (shipped via atomic worktree refactor)
**Supersedes:** —
**Superseded by:** [`../unified-training-pipeline/`](../unified-training-pipeline/)(2026-05-16)

> **Superseded by:** [`../unified-training-pipeline/`](../unified-training-pipeline/)(2026-05-16)
>
> ADR-0006 立约 `framework/ + az/ + cfr/ 零互 import` 已被 P5-F framework 删除整体替代;
> unified pipeline 改为 `training/core/` + `training/paradigms/<name>/` 二分;
> framework 内容 mv 到 `training/core/`(部分)+ `training/paradigms/<name>/legacy/`(AZ/CFR 部分)。
>
> 原 ADR 内容保留作历史决策档案,以下 Why / What / Affected specs 段落维持原样不改。

## Why

`training/` 49 个文件触发 300 行 pre-commit 上限;大部分问题源于 AZ 与 CFR 混在同一命名空间:
- 既有 AZ-only 代码 (selfplay, mcts)
- 又有 CFR-only 代码 (traversal, reservoir)
- 外加两者共享的异步训练循环 / worker pool / inference server 散落在顶层 `_*` 前缀文件

单一拆分无法同时解决 "行数" 与 "命名空间污染"。

## What

三层单向依赖:

- **`framework/`** — 算法无关基础设施
  - obs 常量、step 编码、结构值
  - inference server
  - matchup 运行框架
  - buffer 去重基类 (`StaticDedupBufferBase`)
  - `AgentBase`
  - `TrainingConfig` 基类
- **`az/`** — AlphaZero 专属
  - selfplay / mcts / determinize / priority replay
  - actor-critic / train_step / async loop
  - arena / config_loader
- **`cfr/`** — Deep CFR 专属
  - traversal / reservoir / CFRAgent
  - advantage/strategy/value fit

**约束**:AZ ⟷ CFR 零互 import;两者都只 import framework;framework 不 import 任何上层。

**关键抽象决策**:
- `AgentBase` 提取(原 `CFRAgent(Agent)` 跨包继承);AZ Agent / CFRAgent 各自继承
- `StaticDedupBufferBase` 提取 game-static 去重 + refcount 共享生命周期;淘汰策略 (AZ ring / CFR
  Vitter-R) 保留子类;dynamic key 验证 + sample() 语义不同不抽
- `CollectorBuffer` **不**抽(subagent 审查:无 refcount / 无淘汰,语义与 reservoir 差异大,强抽是
  成本净增,duck-type 保留)
- Traversal 5 分 + Mixin:1035L 大户拆 encoding / config / traverser / os_sampling / es_sampling;
  `CFRTraverser(TraverserBase, OSMixin, ESMixin)`
- `parallel_inference` 归 az/:它 import `selfplay` + `mcts.compute_annealed_lambda`,AZ-specific worker
  pool,不进 framework
- `MCTSPlayer` 上提到 framework:原 `matchup.py` import `tools.mcts_player` 是层序倒置,MCTSPlayer
  无 `training.*` 依赖,promote 到 `framework/matchup/players.py`
- `DEFAULT_SOCKET_PATH` 内联:原 `_train_helpers` import `tools.eval_service.DEFAULT_SOCKET_PATH` 形成
  循环;`framework/gauntlet.py` 内联常量断开

**无 shim** — 按用户原则 "大改造不保留向后兼容":一次原子工作树,旧路径全部删除,所有 call site
(tools/、web/、tests/) 同状态更新,**不保留任何名字级别的向后兼容别名**(`c1_config` /
`TrainAZConfig` / `_compute_structural_obspos` / `TrainConfig` / `_CFRReservoirBase` /
`_resolve_pool_refs` / `_make_pool_spec` / `_health_check` / `_rollout` 等旧名全部重命名,外部引用
同步改新名)。

## Affected specs

- `training-architecture` (本 ADR 是 source spec 的依据,P1+ 抽 SHALL invariants 时 backfill)
