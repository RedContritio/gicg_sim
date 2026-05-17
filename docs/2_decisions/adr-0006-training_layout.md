# 训练层三层拆分(framework/az/cfr)

> **MOVED to `openspec/changes/archive/0006-training-layout/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0006-training-layout/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0006-training-layout/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**日期:** 2026-04-23

## 问题

`training/` 49 个文件触发 300 行 pre-commit 上限;大部分问题源于
AZ 与 CFR 混在同一命名空间,既有 AZ-only 代码(selfplay, mcts)
又有 CFR-only 代码(traversal, reservoir),外加两者共享的异步训练
循环、worker pool、inference server 都散落在顶层 `_*` 前缀文件里。
单一拆分无法同时解决"行数"与"命名空间污染"。

## 方案

三层单向依赖:

- `framework/` — 算法无关基础设施(obs 常量、step 编码、结构值、
  inference server、matchup 运行框架、buffer 去重基类、AgentBase、
  TrainingConfig 基类)
- `az/` — AlphaZero 专属(selfplay、mcts、determinize、priority
  replay、actor-critic、train_step、async loop、arena、config_loader)
- `cfr/` — Deep CFR 专属(traversal、reservoir、CFRAgent、
  advantage/strategy/value fit)

AZ ⟷ CFR 零互 import;两者都只 import framework。framework 不 import
任何上层。

## 对抽象层的关键决策

- **AgentBase 提取**:原 `CFRAgent(Agent)` 跨包继承,v6.3 改为
  `AgentBase` 在 framework,AZ Agent 与 CFRAgent 各自继承。
- **StaticDedupBufferBase**:AZ ReplayBuffer 与 CFR Reservoir 原本
  各自实现 game-static 去重 + refcount。提取共享生命周期到 framework;
  淘汰策略(AZ ring vs CFR Vitter-R)保留子类。Dynamic key 验证、
  sample() 语义不同,不抽。
- **CollectorBuffer 不抽**:subagent 审查发现它没 refcount、不做淘汰,
  语义与 reservoir 差异大,强抽是成本净增。Duck-type 保留。
- **Traversal 5 分 + Mixin**:1035L 大户拆为 encoding / config / traverser /
  os_sampling / es_sampling;`CFRTraverser(TraverserBase, OSMixin, ESMixin)`。
- **parallel_inference 归 az/**:它 import `selfplay` + `mcts.compute_annealed_lambda`,
  是 AZ-specific worker pool,不进 framework。
- **MCTSPlayer 上提到 framework**:原 `matchup.py` import `tools.mcts_player`
  是层序倒置;MCTSPlayer 无 `training.*` 依赖,promote 到
  `framework/matchup/players.py`。
- **DEFAULT_SOCKET_PATH 内联**:原 `_train_helpers` import
  `tools.remote.eval_service.DEFAULT_SOCKET_PATH` 形成循环;framework/gauntlet.py
  内联常量断开。

## 无 shim

按用户原则"大改造不保留向后兼容":一次原子工作树,旧路径全部删除、
所有 call site(tools/、web/、tests/)同一状态更新,**不保留任何
名字级别的向后兼容别名**(`c1_config` / `TrainAZConfig` /
`_compute_structural_obspos` / `TrainConfig` / `_CFRReservoirBase` /
`_resolve_pool_refs` / `_make_pool_spec` / `_health_check` / `_rollout` 等
旧名全部重命名,外部引用同步改为新名)。

## 审查

此方案经过 4 轮 subagent 审查迭代(v6 → v6.1 → v6.2 → v6.3 → end-review),
每轮排查 blocker 后修正:
- v6 → v6.1: 6 项(pool-spec 公开化、MCTSPlayer 上提、
  DEFAULT_SOCKET_PATH 内联、traversal 5 分、buffer 基类正名、
  TrainConfig 改名)
- v6.1 → v6.2: 2 项(parallel_inference 归 az/、buffer 共享面收窄)
- v6.2 → v6.3: 2 项(AgentBase 跨包继承、step_encoding + structural 提取)
- end-review: 3 项(config_loader / arena / async_loop 归 az/,
  移除 7 处 agent 自作主张的向后兼容别名,移除 1 处 F401 re-export shim)

## 验证

- `tools._meta.check_line_limits training/` = 0 violations
- `pytest training/tests gicg_env/tests -n 2` 全绿 (394 passed)
- `ruff format --check` 通过
