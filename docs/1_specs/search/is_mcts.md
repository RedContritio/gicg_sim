# MCTS 算法设计

> **MOVED to `openspec/specs/search-ismcts/`**（2026-05-15，P1-T3）
>
> 本文档内容已迁到 OpenSpec（SHALL 语言），按 3 subtopic 拆分:
> - [Algorithm](../../../openspec/specs/search-ismcts/algorithm.md) — IS-UCT 选择 / 扩展 / 叶节点评估 / 回传 / Dirichlet / 温度
> - [Tree structure](../../../openspec/specs/search-ismcts/tree-structure.md) — `MCTSNode` / 复合动作粒度 / 转置表 prohibition / 连招发现 / 快照
> - [Determinization](../../../openspec/specs/search-ismcts/determinization.md) — CardPoolSpec / 隐藏状态采样 / 引擎注入
> - 顶层 spec:[search-ismcts/spec.md](../../../openspec/specs/search-ismcts/spec.md)
>
> 本文件保留至 P1++（`docs/1_specs/` 整体清理）；**只读**。

---

> 相关决策：`decisions.md` D1（Python）、D2（IS-UCT 单树）、
> D12（复合动作粒度，无抽象，无转置表）、
> D13（基于检查点的发现机制）。
>
> **Backend**: 2026-04-19 起支持 `[mcts] backend = "go"` TOML 开关，
> 将整棵树 + 所有 rollout 路径移到 Go (`gicg_mcts/` package)。
> 本文档描述的算法 (IS-UCT + 确定化 + λ-mixing) 两侧完全一致；
> Python 版 (`training/az/mcts/`) 保留作参考实现 + agent-backed
> 测试路径。Go 版通过 cgo callback 拉 Python 做 leaf eval，
> 保持 inference_server 协议不变。
> 迁移决策包见 `../../2_decisions/adr-0004-is_mcts_migration.md`.

## 算法：信息集 MCTS（IS-UCT）

本 MCTS 采用 **IS-UCT（Cowling 2012）**——单树信息集 MCTS。
通过对每次 rollout 的隐藏状态进行确定化处理来应对不完全信息
（对手手牌、对手牌库顺序、对手骰子、未来抽牌），
并使用 `N_avail` 记录来正确评估仅在部分 rollout 中合法的动作。

**参考文献**：Cowling, Powley, Whitehouse (2012). "Information Set
Monte Carlo Tree Search." IEEE Trans. on CIAIG.

## 树结构

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

**关键：`N_avail[a]`** 统计的是在所有 rollout 中，动作 `a` 在该节点
下降过程中**合法且被纳入选择考量**的次数。这与 `N(a)` 不同——
`N(a)` 统计的是 `a` 实际**被访问**的次数。

`N_avail` 的重要性在于：对手的合法动作集在不同 rollout 之间会有所不同
（不同的确定化 → 对手手牌不同 → 可打出的手牌动作不同）。
一个很少合法的动作不应仅因其很少被纳入范围就在 UCB 下显得"未被探索"。

**智能体自身的动作**在各确定化之间是稳定合法的
（自己的手牌内容对自己是公开的，在 AP 视同万能骰的 MVP 阶段
骰子等价性是平凡的）。只有对手节点需要处理合法性过滤。
相比通用 IS-MCTS 场景，这是一项重大简化。

## 选择：带 N_avail 的 PUCT

在下降过程中，每个非终止非叶节点选择使以下公式最大化的子节点：

```
PUCT(s, a) = Q(s, a) + c_puct * P(a|s) * sqrt(N_avail(s, a)) / (1 + N(s, a))
```

其中：
- `Q(s, a) = W(s, a) / max(1, N(s, a))`，从父节点所属玩家的视角计算
  （当父节点轮次为 P1 时取反，因为 W 以 P0 视角存储）
- `P(a|s)` 是网络对动作 `a` 给出的策略先验
- `c_puct` 是探索常数（标准值 1.4，可调）
- 探索奖励中的 `N_avail` 确保合法性较低的动作在合法时仍能获得适当的探索权重

**只考虑当前确定化下合法的子节点。** 非法动作在选择阶段被完全跳过。

## 扩展

当下降到达一个存在子节点占位符但部分尚未展开的节点时，
选择第一个未展开的合法子节点，步进环境，并创建新节点：

```python
def expand(parent, action_idx, env):
    env.step(action_idx)
    new_node = MCTSNode(
        turn=env.current_player,
        terminal=env.done,
        winner=env.winner if env.done else -1,
    )
    if not new_node.terminal:
        legal = env.get_legal_actions()
        new_node.n_legal = len(legal)
        new_node.children = [None] * new_node.n_legal
        new_node.prior = network.policy_forward(env.obs())  # PUCT prior
        new_node.leaf_value = network.value_forward(env.obs())  # backup init
    parent.children[action_idx] = new_node
    return new_node
```

## 叶节点评估：AlphaGo-mode 网络 + rollout 混合

原始 AZ 设计使用纯网络价值作为叶节点价值。C1v1 验证（见
`c1_postmortem.md`）证明，在 d_model=64 / 2000 局规模下，网络价值作为
leaf eval 严重劣于随机 rollout（IS-MCTS + 随机网络 value 对 random
仅 20%；换成 random rollout 价值则达到 90%）。

shipped 实现（`training/az/mcts/`）采用 **AlphaGo 模式混合**：

```python
# pseudocode of training/az/mcts/
leaf_v = network_value if node is not terminal else _p0_value(winner)
if rollout_value is not None and config.value_mix_lambda < 1.0:
    lam = config.value_mix_lambda
    leaf_v = lam * leaf_v + (1 - lam) * rollout_value
# prior 同样支持与 uniform 的混合
if config.prior_mix_lambda < 1.0:
    prior = plam * network_prior + (1 - plam) * uniform
```

- `value_mix_lambda = 1`：纯网络价值（原 AZ 模式，C1v1 已证劣于 rollout）
- `value_mix_lambda = 0`：纯 rollout 价值（C1v2 验证通过）
- `value_mix_lambda ∈ (0, 1)`：混合模式

C1v4 采用 **线性退火**（`lambda_anneal_games` 控制）：从 0 起步，
线性增长至 `lambda_end`（典型 0.8）。早期借助 rollout 基线避免
网络噪声毒化搜索，后期网络质量提升后逐步接管。

自举停滞时仍可切换为启发式 rollout（D6 升级方案第 3 条），但
C1v2/v4 经验表明纯 random rollout 已足够在 MVP 规模上稳定启动。

## 回传

在返回树的路径上，路径中每个节点的 `N` 和 `W` 均递增：

```python
def backup(path, leaf_value):
    # leaf_value is already from P0's perspective
    for node in path:
        node.N += 1
        node.W += leaf_value
        # Update N_avail for all children that were legal at this node
        for a in legal_actions_at_node:
            node.N_avail[a] += 1
```

注意：`N_avail` 针对路径上每个节点的**所有**合法子节点更新，
而不仅是被选择的那个——这是 IS-UCT 对标准 UCT 回传的变体。

## 复合动作粒度

每个决策点的合法动作列表是 `(种类 × 骰子组合 × 目标 × 调音来源)` 的
**完整笛卡尔积**。不做抽象，不做延迟规划。
拒绝抽象方案的理由详见 D12。

影响：
- `MAX_ACTIONS` 必须能容纳最坏情况的枚举：MVP 阶段为 128，
  在重度灵活费用场景下可能增长到 256
- 合法动作枚举由引擎侧 `GameGetLegalActions` 负责，
  必须对支付多重集去重（详见 `dice_spec.md`）
- 策略头输出词表大小 = `MAX_ACTIONS`，各动作特征包含骰子组合分解
  （详见 `network_design.md`）

## 转置表：**不使用**

不同路径到达相同"最终资源状态"的情况保持为独立树节点。原因如下：

1. **中间状态不同。** 节点代表的不仅是当前游戏状态，还有到达此处的路径。
   两条路径在计数器/HP/骰子状态上收敛一致，但可能具有不同的钩子激活历史，
   或存在顺序敏感效果（如 buff 作用于不同的上场角色）。

2. **价值头学习目标。** 训练时，价值头以自对弈轨迹中的（状态，结局）对作为目标。
   若两条路径产生相同状态但因 buff 附着在不同角色上而产生不同的后续行为，
   合并它们会污染价值目标。

D12 中两个具体示例（先调音后换人 vs 先换人后调音，
以及先加 buff 后换人 vs 先换人后加 buff）表明：
路径信息具有语义意义，而非仅是流程细节。使用转置表是不合理的。

## 连招发现：基于检查点的 argmax 比较

在单次 MCTS 搜索中，在多个 rollout 数量检查点（如 `[50, 100, 200, 400]`）
记录 `argmax_visits(root)`。搜索完成后检查：

```python
best_early = argmax at checkpoint 50
best_late  = argmax at checkpoint 400
stable_late = (argmax at 200) == (argmax at 400)

if best_early != best_late and stable_late:
    mark_as_discovery_event()
```

该信号是**相对的**（比较同一根节点在不同搜索深度的树状态）和
**二元的**（动作是否改变），**不需要任何绝对阈值**。

拒绝方案的理由详见 D13（已拒绝：绝对 Q 跳跃阈值、同级 Q 比较）。
发现事件的下游使用方式详见 `training_loop.md`
（模式 A = 轨迹优先级，模式 B = 扩展搜索预算）。

## 根节点 Dirichlet 噪声

在根节点开始搜索前，向策略先验中混入 Dirichlet 噪声以促进探索：

```python
noise = np.random.dirichlet([alpha] * n_legal)
root.prior = (1 - eps) * network_prior + eps * noise
```

标准 AZ 参数：`alpha=0.3, eps=0.25`。若自举停滞，
参见 D6 升级方案第 1 条以提升这些值。

**仅在根节点添加**，不在内部节点添加。内部节点的探索自然由 PUCT 提供。

## 温度调度

在自对弈中，根节点的动作选择使用温度缩放采样（基于访问次数，而非纯 argmax）：

```python
def sample_action(root, step, tau_threshold):
    if step < tau_threshold:
        # Temperature = 1: sample proportional to visit count
        probs = visits / visits.sum()
    else:
        # Temperature = 0: argmax
        probs = onehot(argmax(visits))
    return np.random.choice(len(probs), p=probs)
```

标准 AZ：`tau_threshold = 15`（前 15 步使用 τ=1，之后使用 τ=0）。
评估阶段（非自对弈）始终使用 τ=0。

## 快照/恢复用于树下降

从根节点开始的 MCTS 下降在根节点处调用一次 `env.snapshot()`，
然后在每次 rollout 开始时调用 `env.restore(snap)`。
每次 `restore` 会推进快照内部的 RNG，使各 rollout 自动获得不同的随机结果——
**这就是机会节点（掷骰子、抽牌）的处理方式**。
MCTS 中没有显式的机会节点机制。

底层原语详见 `gicg_engine/game.go::DeepCopy` 和 `RestoreFrom`（第 170-276 行）。
性能数据详见 `evidence/bench_snapshot.md`。

## 伪代码

```python
def mcts_search(env, root_obs, network, n_rollouts, config):
    root_snap = env.snapshot()
    root = create_root_node(env, network, root_obs)
    root.prior = add_dirichlet_noise(root.prior, config)

    checkpoints = {50: None, 100: None, 200: None, 400: None}

    for i in range(n_rollouts):
        env.restore(root_snap)
        path = [root]
        node = root

        # Selection
        while node.N > 0 and not node.terminal:
            legal = determine_legal_under_this_rollout(node, env)
            # Update N_avail for all legal children
            for a in legal:
                if node.children[a] is not None:
                    node.children[a].N_avail += 1

            if all children expanded:
                a = select_by_puct(node, legal, config.c_puct)
            else:
                a = first unexpanded legal child
                expand(node, a, env, network)
                break

            env.step(a)
            node = node.children[a]
            path.append(node)

        # Backup
        leaf_val = node.leaf_value if not node.terminal else p0_value(node.winner)
        for p in path:
            p.N += 1
            p.W += leaf_val

        # Record checkpoint
        if i in checkpoints:
            checkpoints[i] = argmax_visits(root)

    # Discovery detection
    is_discovery = (checkpoints[50] != checkpoints[400]
                    and checkpoints[200] == checkpoints[400])

    env.restore(root_snap)  # leave env in root state
    env.snapshot_free(root_snap)
    return {
        "visits": root.visit_array(),
        "best_action": argmax_visits(root),
        "value": root.W / root.N,
        "is_discovery": is_discovery,
    }
```

## 待解决的实现问题

- **未展开子节点的先验回退**：在所有子节点展开之前的选择阶段，
  `Q(s, a)` 未定义。标准 UCT 对未访问节点回退到 `Q = inf`，
  AZ 使用 `Q = 0`（或父节点的 Q）。选择其一以保持一致性。
- **`N_avail` 初始化**：第一次访问某节点时，所有合法子节点的
  `N_avail` 从 0 开始。该节点第一次访问的回传将所有合法子节点的
  `N_avail` 递增为 1。请验证这是否符合 Cowling 2012 的公式定义。
- **Rollout 深度限制**：若 MCTS 到达深度 N 的扩展节点仍未终止，
  使用网络价值作为叶节点价值。标准 AZ 没有深度限制（网络始终提供价值），
  但添加 `max_search_depth=100` 作为安全围栏，以防出现病态对局。
