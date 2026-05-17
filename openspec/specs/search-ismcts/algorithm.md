---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-ismcts
subtopic: algorithm
---

# Algorithm — IS-UCT 选择 / 扩展 / 叶评估 / 回传 / 探索

> 本 subtopic 锚定 GICG IS-MCTS 的算法本体 — 选择(PUCT + N_avail)、
> 扩展、叶节点评估(AlphaGo 模式 λ-mixing)、回传、根节点 Dirichlet 噪声、
> 温度调度。`MCTSNode` 数据结构与复合动作粒度见 [`./tree-structure.md`](./tree-structure.md);
> 确定化采样流程见 [`./determinization.md`](./determinization.md)。

## 1. IS-UCT 单树

### 1.1 SHALL invariants

1. Search SHALL use Information Set MCTS(IS-UCT,Cowling 2012)— 一棵
   信息集树跨所有 rollout / 确定化共享。SHALL NOT use per-determinization
   独立树。
2. Each rollout SHALL execute under a freshly sampled determinization
   (新 hidden state),由 snapshot RNG 推进保证不同 rollout 见到不同
   随机结果。详 [`./determinization.md`](./determinization.md) §3。
3. Selection at any node SHALL only consider children that are
   **legal under the current rollout's determinization** — 不合法动作
   完全跳过。
4. Agent 自身动作在所有确定化下稳定合法(自己手牌对自己公开,AP-as-
   wildcard MVP 阶段骰子等价性平凡),因此**仅对手节点**需要合法性
   过滤。

参考:Cowling, Powley, Whitehouse(2012)"Information Set Monte Carlo
Tree Search." IEEE Trans. on CIAIG.

## 2. 选择:PUCT with N_avail

### 2.1 SHALL invariants

1. At each non-terminal non-leaf node, selection SHALL maximize:

   ```
   PUCT(s, a) = Q(s, a) + c_puct · P(a|s) · sqrt(N_avail(s, a)) / (1 + N(s, a))
   ```

   其中:
   - `Q(s, a) = W(s, a) / max(1, N(s, a))`,从父节点所属玩家的视角
     (W 以 P0 视角存储,父节点轮次为 P1 时取反)
   - `P(a|s)` 是网络对动作 `a` 的策略先验
   - `c_puct` 是探索常数(标准值 1.4,可调)
   - 探索项分子用 `sqrt(N_avail)` 而非 `sqrt(parent.N)` —— 这是 IS-UCT
     的核心修正,确保合法性较低的动作在合法时仍获得适当探索权重

2. Selection SHALL skip illegal children entirely(不进入 argmax 比较)。

3. 当节点存在子节点占位符但部分尚未展开时,SHALL select the first
   unexpanded legal child(扩展阶段,见 §3)。

## 3. 扩展 + 叶节点评估

### 3.1 扩展 SHALL invariants

1. Expand SHALL step env to the resulting state and create a new
   `MCTSNode` populated with:
   - `turn`(下一个轮次玩家)
   - `terminal`(`env.done`)、`winner`(若 terminal,`env.winner`,否则
     `-1`)
   - `n_legal`(若非 terminal,合法动作数)
   - `children = [None] * n_legal`(lazy 占位)
   - `prior = network.policy_forward(env.obs())`(供 PUCT 探索使用)
   - `leaf_value = network.value_forward(env.obs())`(供 backup 初始化)

2. Network forward(`policy_forward` + `value_forward`)SHALL be the
   only network call per expanded leaf — 不在 selection / backup 阶段
   重复调用。

### 3.2 叶节点评估 AlphaGo-mode

C1v1 验证(见 `docs/5_history/c1_postmortem.md` history 对应)证明,在
d_model=64 / 2000 局规模下,纯网络价值作为 leaf eval 严重劣于 random
rollout(IS-MCTS + 随机网络 value vs random 仅 20%;换 random rollout
达 90%)。shipped 算法采用 **AlphaGo 模式混合**:

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

### 3.3 SHALL invariants — leaf eval

1. Leaf evaluation SHALL combine **network value + optional rollout
   value** via λ-mixing — `leaf_v = λ · network_v + (1-λ) · rollout_v`。
2. `value_mix_lambda = 1` 退化为纯网络价值(原 AZ 模式,C1v1 失败);
   `value_mix_lambda = 0` 为纯 rollout(C1v2 验证通过);
   `value_mix_lambda ∈ (0, 1)` 为混合模式。
3. λ-anneal SHALL follow linear schedule — 从 `0` 起步,经
   `lambda_anneal_games` 步线性增至 `lambda_end`(典型 0.8)。早期
   rollout 抑制网络噪声毒化,后期网络接管。
4. Prior mixing(`prior_mix_lambda`)SHALL follow analogous linear
   schedule against uniform prior;`prior_mix_lambda = 1` 为纯网络
   prior。
5. λ 的具体值(`value_mix_lambda` / `prior_mix_lambda` /
   `lambda_anneal_games` / `lambda_end`)SHALL be cfg-driven,不在
   本 spec 锁定数值。
6. Rollout 默认 random;启发式 rollout(D6 升级方案第 3 条)为可选
   降级路径,SHALL NOT 默认启用。

## 4. 回传

### 4.1 SHALL invariants

1. Backup SHALL traverse the path from root to leaf (inclusive) and for
   each visited node:
   - 递增 `N` by 1
   - 累加 `W += leaf_value`(`leaf_value` 已以 P0 视角计)
2. Backup SHALL increment `N_avail[a]` for **every legal child a** at
   each visited node — 不仅是被选中的那个。这是 IS-UCT 对标准 UCT 回传
   的关键变体,确保 N_avail 准确记录"合法且被纳入考虑"的次数。
3. Backup SHALL NOT propagate value past the leaf node 's incoming
   edge — terminal leaf 用 `_p0_value(winner)`,非 terminal leaf 用
   `network value (+ optional rollout mix)`。

```python
def backup(path, leaf_value):
    # leaf_value is already from P0's perspective
    for node in path:
        node.N += 1
        node.W += leaf_value
        for a in legal_actions_at_node:
            node.N_avail[a] += 1
```

## 5. 根节点 Dirichlet 噪声

### 5.1 SHALL invariants

1. Before starting search at root, root prior SHALL be mixed with
   Dirichlet noise:

   ```python
   noise = np.random.dirichlet([alpha] * n_legal)
   root.prior = (1 - eps) * network_prior + eps * noise
   ```

2. 标准 AZ 参数:`alpha=0.3, eps=0.25`。SHALL be cfg-driven;若自举停滞
   可加大(参见 D6 升级方案第 1 条)。
3. Dirichlet 噪声 SHALL ONLY be added at root — 内部节点不加。内部
   节点的探索由 PUCT 自然提供。
4. 评估 / arena / gauntlet 阶段(非自对弈)SHALL NOT inject Dirichlet
   noise(确保评估用确定 policy)。

## 6. 温度调度

### 6.1 SHALL invariants

1. Self-play action sampling at root SHALL use temperature-scaled
   visit counts:

   ```python
   def sample_action(root, step, tau_threshold):
       if step < tau_threshold:
           probs = visits / visits.sum()   # τ=1
       else:
           probs = onehot(argmax(visits))  # τ=0
       return np.random.choice(len(probs), p=probs)
   ```

2. 标准 AZ:`tau_threshold = 15`(前 15 步 τ=1,之后 τ=0)。SHALL be
   cfg-driven。
3. 评估阶段(arena / gauntlet / inference)SHALL always use τ=0
   (argmax),不受 `tau_threshold` 影响。
4. Sampling SHALL be on **root visit counts**,而非 root prior;访问
   分布是 MCTS 的输出"policy improvement",prior 仅是输入。

## 7. 完整算法伪代码

```python
def mcts_search(env, root_obs, network, n_rollouts, config):
    root_snap = env.snapshot()
    root = create_root_node(env, network, root_obs)
    root.prior = add_dirichlet_noise(root.prior, config)

    checkpoints = {50: None, 100: None, 200: None, 400: None}

    for i in range(n_rollouts):
        env.restore(root_snap)
        # 采样隐藏状态 + 注入 — 见 ./determinization.md §3
        hidden = sample_hidden_state(env, viewing_player, card_pool_spec, rng)
        apply_determinization(env, hidden, opponent=1-viewing_player)

        path = [root]
        node = root

        # Selection
        while node.N > 0 and not node.terminal:
            legal = determine_legal_under_this_rollout(node, env)
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

        # Leaf eval + backup
        leaf_val = node.leaf_value if not node.terminal else p0_value(node.winner)
        if rollout_enabled and value_mix_lambda < 1.0:
            rv = random_rollout_value(env)
            leaf_val = value_mix_lambda * leaf_val + (1 - value_mix_lambda) * rv
        for p in path:
            p.N += 1
            p.W += leaf_val
            # N_avail incremented inline during selection

        # Discovery checkpoint(见 ./tree-structure.md §4)
        if i in checkpoints:
            checkpoints[i] = argmax_visits(root)

    is_discovery = (checkpoints[50] != checkpoints[400]
                    and checkpoints[200] == checkpoints[400])
    env.restore(root_snap)
    env.snapshot_free(root_snap)
    return {
        "visits": root.visit_array(),
        "best_action": argmax_visits(root),
        "value": root.W / root.N,
        "is_discovery": is_discovery,
    }
```

## 8. 待解决问题

以下问题保留作 implementation 决策点 — 当前 shipped 实现已选定路径,
但属于实现细节而非 SHALL 锁定项:

- **未展开子节点的 Q fallback**:在所有子节点展开前,`Q(s, a)` 未定义。
  标准 UCT 用 `Q = inf`(乐观);AZ 用 `Q = 0`(中性)或父节点 Q。
  shipped 选其一保持 Python ↔ Go 一致。
- **`N_avail` 初始化**:第一次访问某节点时,所有合法子节点 `N_avail`
  从 0 开始。首次回传将所有合法子节点 `N_avail` 递增为 1。验证是否
  符合 Cowling 2012 公式定义。
- **Rollout 深度限制**:若 MCTS 到达深度 N 仍未终止,使用网络价值作为
  叶节点价值。标准 AZ 无深度限制(网络始终提供价值),但 shipped
  添加 `max_search_depth=100` 作安全围栏,防病态对局。
