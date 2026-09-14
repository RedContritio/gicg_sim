---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-ismcts
---

# Search IS-MCTS — 信息集 MCTS + 确定化采样规约

> 本 capability spec 治理 GICG 的 shipped 搜索算法 — 信息集 MCTS
> (IS-UCT,Cowling 2012)+ 确定化采样器(CardPoolSpec)。算法在 Python
> (`training/az/mcts/`) 与 Go(`gicg_mcts/`)两侧实现完全一致,本 spec
> 不区分 backend(差异仅是 cgo callback 路径,不动算法语义)。
>
> 本 spec 从 `docs/1_specs/search/is_mcts.md`(305 行)+
> `docs/1_specs/search/determinization.md`(221 行)抽取规约,SHALL 化
> + 按 3 subtopic 拆分。设计推导 + 历史 ablation(C1v1 leaf eval 失败 /
> C1v2 rollout 验证)保留在 `docs/5_history/` 各 postmortem。
>
> 与 `openspec/specs/search-parallel/`(并行推理 + 异步流水)互补:本
> capability 治理算法本体,search-parallel 治理进程拓扑。

## 1. Purpose

GICG 搜索需被规约化,否则会出现:

- IS-UCT 关键不变量(`N_avail` 记账、合法性过滤、根节点 Dirichlet 噪声)
  在 Python ↔ Go 跨 backend 移植时静默偏离
- C1v1 leaf eval 失败教训(纯网络价值在 d_model=64 / 2000 局规模严重劣于
  random rollout,IS-MCTS + random network value 对 random 仅 20%)被新
  paradigm 重蹈,设计契约(AlphaGo 模式 λ-mixing)需 SHALL 锁定
- 复合动作粒度(完整笛卡尔积,不抽象,不延迟规划)+ 转置表 prohibition
  (D12)在引擎/搜索 refactor 中静默重新引入
- 确定化采样器的 `CardPoolSpec` 接口契约 + max_copies 约束 + 公开信息
  减去流程在升级到 UniformFromPool / BayesianFromPlayHistory 时被破坏

本 spec 提供 3 大类约束:

- **Algorithm**(详 [`./algorithm.md`](./algorithm.md))— IS-UCT 选择 / 扩展 / 叶节点评估 / 回传 / Dirichlet / 温度
- **Tree structure**(详 [`./tree-structure.md`](./tree-structure.md))— 节点字段 / 复合动作粒度 / SHALL NOT 转置表 / 连招发现 / 快照恢复
- **Determinization**(详 [`./determinization.md`](./determinization.md))— CardPoolSpec / 隐藏状态采样 / 注入引擎 / rollout 流程

## 2. Scope

**In scope**:

- IS-UCT 单树算法本体(选择 / 扩展 / 回传 / Dirichlet / 温度)
- `MCTSNode` 数据结构契约(N / W / N_avail / prior / leaf_value)
- 叶节点评估(AlphaGo 模式:network value + optional rollout,λ-mixing
  schedule)
- 确定化采样器(`CardPoolSpec` 接口 + 3 实现:SharedFixedPool /
  UniformFromPool / BayesianFromPlayHistory)
- 隐藏状态注入引擎(`GameSetPlayerHand` / `GameSetPlayerDeck` /
  未来 dice)+ rollout 流程
- 复合动作粒度契约(完整笛卡尔积)+ 转置表 prohibition

**Out of scope**:

- 并行推理拓扑(server + worker 进程模型)— 由
  [`openspec/specs/search-parallel/`](../search-parallel/spec.md) 治理
- 网络结构(value/policy/delta head,encoder)— 由
  [`openspec/specs/network-architecture/`](../network-architecture/spec.md) 治理
- `λ-mixing` 的具体数值 / 经验值(`value_mix_lambda` /
  `lambda_anneal_games` / `lambda_end`)— 由各 paradigm cfg / run dossier
  治理,本 spec 仅约束 anneal 行为
- 各 paradigm 的算法层(CFR regret 更新、BC dataset 生成)— 不使用
  IS-MCTS,不属本 spec 范围

## 3. Core SHALL invariants

以下 10 条 invariant 是本 capability 的硬约束。任意冲突应作为
OpenSpec change 提案修订,而非在代码中静默偏离。

1. **IS-UCT 单树**:Search SHALL use Information Set MCTS(IS-UCT,
   Cowling 2012)— 单棵树跨所有确定化,**不**使用 per-determinization
   独立树。详 [`./algorithm.md`](./algorithm.md) §1。

2. **N_avail 记账**:Each `MCTSNode` SHALL maintain per-child
   `N_avail[a]` —— 该子节点在所有 rollout 中"合法且被纳入选择"的次数。
   `N_avail` 与 `N` 区分:`N(a)` 是被访问次数,`N_avail(a)` 是合法次数。
   详 [`./tree-structure.md`](./tree-structure.md) §1。

3. **PUCT with N_avail**:Selection SHALL use
   `PUCT(s, a) = Q(s, a) + c_puct · P(a|s) · sqrt(N_avail(s,a)) / (1 + N(s,a))`
   且仅在当前确定化下合法的子节点中选择。详 [`./algorithm.md`](./algorithm.md) §2。

4. **AlphaGo-mode leaf eval**:Leaf evaluation SHALL use **network
   value + optional rollout mix**(`leaf_v = λ · network_v + (1-λ) ·
   rollout_v`),λ 由 paradigm cfg 提供。`λ=1` 退化为纯 AZ 模式(C1v1
   已证劣于 rollout),`λ=0` 为纯 rollout(C1v2 验证),`λ ∈ (0,1)`
   为混合。λ-anneal 行为(线性从 0 起步至 `lambda_end`)由 cfg
   `lambda_anneal_games` 控制。详 [`./algorithm.md`](./algorithm.md) §3。

5. **Backup 路径 + N_avail 全合法子节点**:Backup SHALL propagate
   `leaf_value`(从 P0 视角)沿访问路径递增 `N` / `W`,且对路径上
   每个节点的**所有**合法子节点的 `N_avail` 递增(不仅是被选中的)。
   这是 IS-UCT 对标准 UCT 的关键变体。详 [`./algorithm.md`](./algorithm.md) §4。

6. **SHALL NOT use transposition table**:Tree SHALL NOT collapse
   different paths reaching identical "final resource state" into a
   single node — path history carries semantic meaning(hook activation
   history / buff attachment slot)。详 [`./tree-structure.md`](./tree-structure.md) §3。

7. **Root Dirichlet noise**:Root node SHALL inject Dirichlet noise into
   policy prior(`root.prior = (1-ε) · network_prior + ε · noise`,
   标准 AZ `alpha=0.3, ε=0.25`)— 仅根节点,内部节点不加。详
   [`./algorithm.md`](./algorithm.md) §5。

8. **Temperature schedule**:Self-play action selection SHALL use
   temperature-scaled sampling on root visit counts — `τ=1`(按访问数
   采样)前 `tau_threshold` 步,之后 `τ=0`(argmax)。评估阶段始终用
   `τ=0`。详 [`./algorithm.md`](./algorithm.md) §6。

9. **CardPoolSpec 接口**:Determinization SHALL sample hidden state via
   a `CardPoolSpec` protocol(`sample_opponent_deck` + `max_copies`),
   IS-MCTS 代码不直接依赖具体卡池实现。当前 shipped 用
   `SharedFixedPool`;中长期升级路径(`UniformFromPool` /
   `BayesianFromPlayHistory`)替换实现即可,**不**改 MCTS 代码。详
   [`./determinization.md`](./determinization.md) §1。

10. **Hidden state via clone-snapshot**:Rollout SHALL inject sampled
    hidden state via engine clone-snapshot — 每次 rollout 开始 `env.
    restore(root_snap)` 精确恢复 → 显式 `set_simulation_seed` → 采样 hidden state → `apply_
    determinization(env, hidden, opponent)`(setter API)→ 沿树下降。
    机会节点(掷骰子 / 抽牌)由模拟局的随机流承担,**不**显式建模。
    详 [`./determinization.md`](./determinization.md) §3 + [`./tree-structure.md`](./tree-structure.md) §5。

## 4. Subtopics

本 capability 由本文件 + 3 个 subtopic 组成。每个 subtopic 专注一组
正交规则,主 spec.md 只列 SHALL invariant 概要,细节落 subtopic。

- [Algorithm](./algorithm.md) — IS-UCT 选择(PUCT + N_avail)/ 扩展 /
  叶节点评估(AlphaGo 混合 λ-anneal)/ 回传 / 根节点 Dirichlet / 温度
  调度 / 伪代码 / 待解决问题
- [Tree structure](./tree-structure.md) — `MCTSNode` 字段 / 复合动作
  粒度(完整笛卡尔积)/ 转置表 prohibition(D12)/ 连招发现(基于
  checkpoint 的 argmax 比较)/ 快照恢复
- [Determinization](./determinization.md) — `CardPoolSpec` 接口 + 三
  实现 / 隐藏状态采样流程(对手手牌+牌库+未来骰子)/ 减去公开信息 /
  注入引擎 setter API / 完整 rollout 流程

## 5. Cross-references

**Sibling capability specs**:

- [`openspec/specs/search-parallel/`](../search-parallel/spec.md) —
  并行推理 + 异步训练流水(本 spec 治理算法,search-parallel 治理
  worker/server 进程拓扑)
- [`openspec/specs/network-architecture/`](../network-architecture/spec.md) —
  网络结构(本 spec 的 leaf eval 调网络 value/policy head;network 治理
  head 实现)
- [`openspec/specs/training-architecture/`](../training-architecture/spec.md) —
  paradigm-agnostic training infra(本 spec 的 self-play loop 由 training
  driver 调用,training-architecture 治理 driver / opponent mix /
  buffer)
- [`openspec/specs/engine-dsl/`](../engine-dsl/spec.md) — 引擎 setter API
  契约(`GameSetPlayerHand` / `GameSetPlayerDeck`)+ snapshot/restore
  原语
- [`openspec/specs/openspec-policy/`](../openspec-policy/spec.md) —
  本 spec 的格式与阈值由其治理

**Archived OpenSpec changes**(相关决策):

- `openspec/changes/archive/0004-is-mcts-migration/` — ADR-0004
  Python → Go MCTS backend 迁移决策包
- `openspec/changes/archive/0005-az-decisions-d1-d14/` — AZ 决策日志
  (D1 Python / D2 IS-UCT 单树 / D12 复合动作粒度 + 无转置表 /
  D13 基于 checkpoint 的发现机制)

**History / postmortems**:

- `docs/1_specs/search/is_mcts.md` / `docs/1_specs/search/determinization.md` (deleted, migrated here) —
  本 spec 的 narrative source,已加 deprecation note,保留至 P1++
  整体清理
- [`docs/5_history/search_history.md`](../../../docs/5_history/search_history.md) —
  并行推理实测性能 / MPS GPU 失败 / C1 验证 run 耗时估算(P1-T3 mv 自
  parallel.md L332-383)

## 6. Status

- **Created**:2026-05-15(P1-T3)
- **Version**:0(初始落地)
- **Source**:`docs/1_specs/search/is_mcts.md`(305) +
  `docs/1_specs/search/determinization.md`(221)
- **Expected revision triggers**:
  - λ-mixing schedule 引入新形态(非线性 anneal / loss-adaptive λ)
  - 转置表政策放开(预期不会发生,但若 D12 reopen 需新 change)
  - `CardPoolSpec` 接口扩展(deckbuild 模式下 deck 构成本身未知)
  - 真实骰子上线后 `sample_hidden_state` 加入 dice 维度
