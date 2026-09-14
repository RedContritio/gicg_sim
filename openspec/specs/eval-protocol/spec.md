---
last_updated: 2026-09-14
status: LIVE
schema_version: 0
capability: eval-protocol
---

# Eval Protocol — gauntlet / arena / eval daemon 协议

> 本 capability spec 治理 GICG 的评估栈接口契约 — `tools/eval/eval_service.py`
> 全局 socket daemon(production)、`tools/eval/` paradigm-agnostic
> adapter(P0-T8 ship,新方向)、`training/core/matchup/` 内
> gauntlet / arena / baseline 实现。本 spec 治理**接口与协议**,具
> 体 baseline 算法细节(F1-Dn feature 公式 / mcts_pure UCB 系数)由
> 子 spec / 各 baseline dossier 承接。
>
> **过渡期混合**:`tools/eval/eval_service*.py` 是 production
> localhost TCP daemon(AZ / CFR / 早期 DMC 用);新方向 `tools/eval/*` 是
> paradigm-agnostic poll-based daemon(DMC Phase 3.5 起新建)。两
> 者并存于 P1-P2 阶段,本 spec 同时 SHALL 化二者,以 transitional
> note 标差异。
>
> 本 spec 从 `docs/1_specs/eval/README.md`(原标 "WIP")reverse
> engineer 写成 SHALL 形式,源 truth 是 `tools/eval/eval_service*.py` +
> `tools/eval/*.py` + `tools/eval/eval_service_schema.json` +
> `training/core/matchup/*.py` 当前 shipped 代码。

## 1. Purpose

GICG 评估栈需被规约化,否则会出现:

- TCP request daemon 与 paradigm-agnostic adapter 接口分歧无
  spec 锚定，容易造成 schema 与实现漂移
- Gauntlet / arena / matchup runner 间签名漂移(已发生:swap_sides
  默认值变化、deck_padding 字段添加位置不一致)
- Baseline player(random / F1-Dn / mcts_pure / historical)接口未
  统一,新 paradigm 接入时各自重实现
- DSL cache warming / eval scenario seed determinism / metrics.jsonl
  schema 等约定散在 docstring,新 contributor 反复试错

本 spec 提供 4 大类约束:

- **Eval service**(详 [`./service.md`](./service.md))— socket
  daemon + paradigm-agnostic daemon
- **Gauntlet**(详 [`./gauntlet.md`](./gauntlet.md))— 多 baseline
  matchup tournament
- **Arena**(详 [`./arena.md`](./arena.md))— 1v1 head-to-head
- **Baselines**(详 [`./baselines.md`](./baselines.md))—
  random / F1-Dn / mcts_pure / historical ckpt 接口

## 2. Scope

**In scope**:

- `tools/eval/eval_service.py` localhost TCP protocol(JSON message format,
  job dispatch,DSL cache,heartbeat)
- `tools/eval/eval_service_schema.json` JSON Schema 2020-12(authoritative
  request schema)
- `tools/eval/daemon.py` paradigm-agnostic poll-based daemon(rsync +
  ckpt mtime watch + PeriodicEvaluator 调用)
- `tools/eval/_paradigm.py` paradigm adapter registry
- `training/core/matchup/matchup.py` gauntlet runner(`run_matchup`
  + `CellStats` + `MatchupResult`)
- 历史 `training/az/arena.py` 1v1 arena contract（实现已移除，见
  [`./arena.md`](./arena.md)）
- `training/core/matchup/loaders.py` LOADERS registry
  (az / random / mcts_pure / cfr / greedy)
- `training/core/matchup/players.py` `MCTSPlayer`(pure UCT)
- `training/core/matchup/greedy_player.py` `GreedyPlayer`
  (F1-F5 features × D1-D3 depths × `dice_greedy` flag)
- `tools/eval/metrics_view.py` metrics.jsonl 读取与渲染
- `tools/eval/compare.py` multi-ckpt 比较

**Out of scope**:

- Eval scenario 设计(具体 F1-D2 / F1-D4 评估场景的 team / pool /
  card_pool 组合)— `runs-registry` capability spec(待落地)
- Engine-side 评估(若 Go gauntlet 化 — `gicg_baselines/` 未来 Go
  capability)— 单独 spec
- Network inference path 与 trainer inference 隔离 —
  [`training-architecture/eval`](../training-architecture/eval.md)
- 训练工作流何时运行 gauntlet（流程层，不属于本协议）

## 3. Core SHALL invariants

以下 10 条 invariant 是本 capability 的硬约束。任意冲突应作为
OpenSpec change 提案修订,而非在代码中静默偏离。

1. **Eval service as separate process**:Production gauntlet eval
   SHALL run as a separate process— `tools/eval/eval_service.py`
   listens on localhost TCP(default `localhost:9100`),training runs 通过 JSON message 提交
   job。详 [`./service.md`](./service.md)。

2. **JSON Schema authoritative**:Service SHALL validate every
   incoming request against `tools/eval/eval_service_schema.json` (JSON
   Schema 2020-12)。Schema is **single source of truth**;
   `tools._meta.send_matchup` CLI 与 client 帮助文本 SHALL 由此 schema 生
   成。详 [`./service.md`](./service.md)。

3. **DSL cache across requests**:Service SHALL warm DSL parse cache
   at startup(`preload_dsl(data_dir)`)+ maintain across gauntlet
   jobs。Mid-run DSL edits SHALL NOT affect in-flight / queued jobs
   (cache 已 full,GameNew 不再 touch disk)。详 [`./service.md`](./service.md)。

4. **Gauntlet = N baseline matchups**:`run_matchup` SHALL eval one
   ckpt(challenger)vs N baselines,each baseline 一个 matchup;每
   matchup 内可 `mode=fixed`(指定 team_0 / team_1)或
   `mode=enumerate_disjoint`(char_pool × team_size 枚举所有 disjoint
   team pair)。详 [`./gauntlet.md`](./gauntlet.md)。

5. **Historical arena contract**:已移除的
   `training/az/arena.py::arena_match` 曾在 challenger 和 champion
   间交替先后手。该接口不再是当前实现约束；历史契约保存在
   [`./arena.md`](./arena.md)。

6. **Baseline interface — LOADERS registry**:Player builders SHALL
   register in `training/core/matchup/loaders.py::LOADERS`
   dict(`type` → builder fn)。新 paradigm 接入 SHALL 加 entry,
   SHALL NOT bypass。`tools/eval/_paradigm.py` 是新方向的 paradigm
   adapter registry(独立);两个 registry 并存(transitional),P2
   合并由后续 change 治理。详 [`./baselines.md`](./baselines.md)。

7. **Swap-sides correction**:Eval SHALL support `swap_sides` boolean
   (default `True`)— alternating which side challenger plays in
   `games_per_cell` 双倍展开(2 × games_per_cell)。CFR ckpt 训练
   时 pinned sides 的可 `swap_sides=False`。Mirror-match 双方相同,
   两种设置等价。详 [`./gauntlet.md`](./gauntlet.md)。

8. **Result schema — JSONL**:Eval results SHALL append to
   `result_path` 指定的 JSONL file。Service 每 job append one line:
   `{id, game_marker, players, aggregate, per_cell, wall_s}`。
   `metrics.jsonl`(daemon heartbeat + job_done / job_fail)分离写
   入 service-level metrics path。详 [`./service.md`](./service.md)。

9. **Eval determinism**:Eval scenario SHALL be deterministic given
   `(seed, game_marker)` — 同 seed/marker 跑两次 SHALL 得 byte-identical
   matchup result(modulo PyTorch nondeterminism)。每 cell base seed
   = `seed + ti * 10_000`;每 game = `base + g`。详
   [`./gauntlet.md`](./gauntlet.md)。

10. **Eval inference isolation**:Eval inference SHALL be **independent**
    from train inference — eval worker / service 拥有独立 agent
    instance,SHALL NOT 共享 trainer 的 inference server state。详
    [`training-architecture/eval`](../training-architecture/eval.md);
    本 spec service.md 锚定 process boundary。

## 4. Subtopics

本 capability 由本文件 + 4 个 subtopic 组成。每个 subtopic 专注一组
正交规则。

- [Eval service](./service.md) — `tools/eval/eval_service.py` localhost TCP
  daemon + `tools/eval/daemon.py` paradigm-agnostic poll daemon、
  JSON Schema 验证、DSL cache、heartbeat、metrics.jsonl,transitional
  note 标二者并存
- [Gauntlet](./gauntlet.md) — `run_matchup` 多 baseline 协议、
  `CellStats` / `MatchupResult` schema、mode=fixed vs enumerate_disjoint、
  swap_sides 实施细节、`enumerate_disjoint_teams` 算法
- [Arena（历史）](./arena.md) — 已移除 `arena_match` 的 1v1 协议和
  `ArenaResult` schema，仅用于解释旧记录
- [Baselines](./baselines.md) — `LOADERS` registry 各 player type
  契约(az / cfr / random / mcts_pure / greedy)、historical ckpt
  接入、GreedyPlayer F1-F5 × D1-D3 × dice_greedy axes

## 5. Cross-references

**Sibling capability specs**:

- [`env-config`](../env-config/spec.md) — `GicgEnv` 实例化由 eval
  消费;`step` / `reset` / `clone` 契约
- [`training-architecture/eval`](../training-architecture/eval.md) —
  paradigm-agnostic eval 流程的高层契约(本 spec 是其物理实施
  protocol 详细化)
- [`engine-capi`](../engine-capi/spec.md) — `preload_dsl` /
  `libgicg.dylib` 接口(eval service DSL cache 依赖)
- [`openspec-policy`](../openspec-policy/spec.md) — 本 spec 格式与
  阈值

**Active OpenSpec archive**(cross-cutting):

- [`changes/archive/0011-pool-versioning`](../../changes/archive/0011-pool-versioning/) —
  eval schema `pool` + `deck_padding` 字段引入(SHALL 4)
- [`changes/archive/0008-rl-paradigm-pivot`](../../changes/archive/0008-rl-paradigm-pivot/) +
  [`0009`](../../changes/archive/0009-rl-paradigm-pivot-terminus/) /
  [`0010`](../../changes/archive/0010-rl-research-reopen/) — eval
  栈在 AZ / PPO / CFR pivot 中的角色

**History / source**:

- `docs/1_specs/eval/README.md`(原 placeholder,本 spec 落地后更新
  为 link)

## 6. Status

- **Created**:2026-05-15(P1-T6)
- **Version**:0(初始落地,过渡期 transitional state)
- **Source**:`tools/eval/eval_service*.py` + `tools/eval/*.py` +
  `training/core/matchup/*.py` shipped
  code
- **Expected revision triggers**:
  - `tools/eval/eval_service*.py` 与 `tools/eval/*.py` 合并(P2
    unified-training-pipeline change 一部分)
  - Eval scenario spec 独立(`runs-registry` capability ship 后从本
    spec 抽离)
  - Engine 端 Go gauntlet 化(`gicg_baselines/` capability ship)→
    baselines.md 拆分 Python vs Go 双轨
  - F1-Dn baseline 算法精修(F6+ 或现有公式调整)→ baselines.md
    follow-up
- **Known transitional state**(follow-up tracked):
  - `tools/eval/eval_service.py` TCP request daemon 与 `tools/eval/daemon.py`
    poll daemon **并存**,接口不互通。Spec 同时 SHALL 化,后续合
    并由 OpenSpec change 治理。
  - `eval_service_schema.json` 与 runtime 参数必须一起复核；当前 schema
    已声明 `pool` / `deck_padding` / `deck_0` / `deck_1`。
