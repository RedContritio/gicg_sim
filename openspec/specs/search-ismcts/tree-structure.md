---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-ismcts
subtopic: tree-structure
---

# Tree structure — `MCTSNode` / 复合动作粒度 / 转置表 prohibition / 连招 / 快照

> 本 subtopic 锚定 GICG IS-MCTS 树的数据结构与拓扑约束 — `MCTSNode`
> 字段定义、复合动作粒度(完整笛卡尔积)、转置表 prohibition(D12)、
> 连招发现(基于 checkpoint 的 argmax 比较,D13)、env 快照/恢复。
> 算法本体(选择 / 扩展 / 回传)见 [`./algorithm.md`](./algorithm.md)。

## 1. `MCTSNode` 数据结构

### 1.1 SHALL invariants

1. Each `MCTSNode` SHALL hold the following fields:

   ```python
   @dataclass
   class MCTSNode:
       turn: int                        # player to move at this state
       terminal: bool                   # game-over at this state
       winner: int                      # -1 / 0 / 1 / 2 (draw)
       n_legal: int                     # number of compound actions
       children: list[Optional[Node]]   # per-action child (lazy)
       N: int                           # visit count
       W: float                         # cumulative value from P0 perspective
       N_avail: list[int]               # per-child availability count (IS-UCT)
       prior: np.ndarray                # policy prior from network, per child
   ```

2. `W` SHALL be stored from **P0 perspective**(不论节点 turn 是 P0
   还是 P1);Q 计算时由 selection 阶段根据父节点 turn 取反。
3. `N_avail` SHALL be a per-child array of length `n_legal`,语义为
   "该子节点在所有 rollout 中合法且被纳入选择"的次数 — 与 `N`
   (实际被访问次数)严格区分。
4. `children` SHALL be lazy-allocated — 占位 `None`,只在 expand
   到该 child 时实例化。
5. `prior` + `leaf_value` SHALL be filled at expand time by single
   network forward(详 [`./algorithm.md`](./algorithm.md) §3)。

## 2. 复合动作粒度:完整笛卡尔积

### 2.1 SHALL invariants

1. 每个决策点的合法动作列表 SHALL be the **complete Cartesian product**
   of `(种类 × 骰子组合 × 目标 × 调音来源)` — 不做抽象,不延迟规划。
   拒绝抽象方案的理由见 ADR-0005 D12。
2. `MAX_ACTIONS` 容量 SHALL accommodate worst-case enumeration:
   - MVP 阶段:128
   - 重度灵活费用场景:可能增长到 256
   超出时 SHALL upgrade via OpenSpec change(不静默截断)。
3. 合法动作枚举 SHALL be performed by engine
   (`GameGetLegalActions`)— 必须对支付多重集去重(详
   `dice_spec.md` / engine-dsl capability)。
4. 策略头输出词表大小 SHALL equal `MAX_ACTIONS`,各动作特征包含骰子
   组合分解(详
   [`network-architecture/heads.md`](../network-architecture/heads.md))。
5. SHALL NOT introduce "abstract / lazy planning" 中间动作粒度(如
   "先打牌后想骰子组合") — 拒绝理由见 D12 ADR。

## 3. 转置表 prohibition

### 3.1 SHALL invariants

1. Tree SHALL NOT use a transposition table — 不同路径到达相同"最终
   资源状态"的情况 SHALL remain as **independent tree nodes**。
2. 拒绝转置表的原因:
   - **中间状态不同**。节点代表的不仅是当前游戏状态,还有到达此处的
     路径。两条路径在计数器 / HP / 骰子状态收敛一致,但可能具有不同
     的钩子激活历史,或存在顺序敏感效果(如 buff 作用于不同的上场
     角色)。
   - **价值头学习目标污染**。训练时,价值头以自对弈轨迹中的(状态,
     结局)对作为目标。若两条路径产生相同状态但因 buff 附着在不同
     角色上而产生不同的后续行为,合并它们会污染价值目标。
3. D12 中两个具体示例(先调音后换人 vs 先换人后调音;先加 buff 后换人
   vs 先换人后加 buff)表明:路径信息具有语义意义,而非仅流程细节。
4. 若未来 reopen 该决策,SHALL go through OpenSpec change — 不在
   代码中静默引入。

## 4. 连招发现:基于 checkpoint 的 argmax 比较

### 4.1 SHALL invariants

1. 单次 MCTS 搜索内,在多个 rollout 数量 checkpoint(典型
   `[50, 100, 200, 400]`)SHALL record `argmax_visits(root)`。
2. 搜索完成后检查:

   ```python
   best_early = argmax at checkpoint 50
   best_late  = argmax at checkpoint 400
   stable_late = (argmax at 200) == (argmax at 400)

   if best_early != best_late and stable_late:
       mark_as_discovery_event()
   ```

3. 该信号 SHALL be **relative**(比较同一根节点在不同搜索深度的树
   状态)且 **binary**(动作是否改变),SHALL NOT 依赖任何绝对阈值
   (如 Q 跳跃阈值、同级 Q 比较)。拒绝绝对阈值方案的理由见
   ADR-0005 D13。
4. Discovery 事件下游用法(轨迹优先级模式 A / 扩展搜索预算模式 B)
   见 paradigm-az dossier 的 training-loop subtopic(P1-T8 落地)。
5. checkpoint 列表 SHALL be cfg-driven — 不锁定具体数值,只锁定
   "至少 3 个 checkpoint 用于 early / mid / late 比较"。

## 5. 快照 / 恢复用于树下降

### 5.1 SHALL invariants

1. 从根节点开始的 MCTS 下降 SHALL call `env.snapshot()` once 在根节点,
   存为 `root_snap`,然后每次 rollout 开始 SHALL call `env.restore
   (root_snap)`。
2. `restore` SHALL 精确恢复随机状态，且不得推进快照或源局的 RNG。
   每个 rollout SHALL 在私有模拟局恢复后显式调用 `set_simulation_seed`
   （Go: `SetSimulationSeed`）设置该次采样的随机流；种子 SHALL 由搜索种子
   与 rollout 序号决定，不得依赖 worker 调度顺序。
3. MCTS SHALL NOT have explicit chance node — 机会节点(掷骰子 /
   抽牌)由显式设置的模拟随机流承担,树内只表示玩家决策节点。
4. 搜索结束后 SHALL `env.restore(root_snap)` 一次(留 env 在根节点
   状态)+ `env.snapshot_free(root_snap)` 释放。
5. 底层原语契约(`gicg_engine/game.go::DeepCopy` + `RestoreFrom`)
   由 [`engine-dsl`](../engine-dsl/spec.md) capability 治理,本 spec
   仅约束**使用方式**。
6. 性能数据见 `docs/5_history/evidence/bench_snapshot.md`(若存在)。

## 6. Cross-references

- [`./algorithm.md`](./algorithm.md) — IS-UCT 算法本体(选择 / 扩展 /
  回传 / Dirichlet / 温度)
- [`./determinization.md`](./determinization.md) — 隐藏状态采样 +
  注入引擎
- [`../search-parallel/spec.md`](../search-parallel/spec.md) —
  并行推理 + worker / server 拓扑
- [`../network-architecture/heads.md`](../network-architecture/heads.md) —
  Policy head 输出 `MAX_ACTIONS` 维 logits 与本 spec §2.4 衔接
- [`../engine-dsl/spec.md`](../engine-dsl/spec.md) — `GameGetLegalActions` /
  `GameSnapshot` / `GameRestore` 引擎契约
