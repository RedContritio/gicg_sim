# 确定化采样器

> **MOVED to `openspec/specs/search-ismcts/determinization.md`**（2026-05-15，P1-T3）
>
> 本文档内容已迁到 OpenSpec（SHALL 语言），作为 search-ismcts capability 的 subtopic:
> - [Determinization subtopic](../../../openspec/specs/search-ismcts/determinization.md) — CardPoolSpec / 隐藏状态采样 / 引擎注入 / rollout 流程
> - 顶层 spec:[search-ismcts/spec.md](../../../openspec/specs/search-ismcts/spec.md)
>
> 本文件保留至 P1++（`docs/1_specs/` 整体清理）；**只读**。

---

> 相关决策：`decisions.md` D2（IS-MCTS 单树 + N_avail）、D9（CardPoolSpec 接口）。

## 目的

IS-MCTS 需要从智能体看不到对手隐藏信息的状态出发向前模拟游戏。为了执行模拟，引擎需要一个**具体的**状态——具体来说，是对手的手牌内容、牌库内容/顺序，以及（未来的）骰子颜色。这些在真实游戏中都是隐藏信息。

**确定化** = 在每次 MCTS rollout 时采样一个合理的具体隐藏状态，在该采样状态上运行模拟，并对多次采样的统计数据进行汇总。

Cowling 2012（IS-UCT）在**每次 rollout 开始时**从共享树根节点执行确定化，而不是通过独立的 MCTS 树。`N_avail` 记账确保只在部分确定化中合法的动作不会因访问次数少而受到惩罚。

## 需要采样的隐藏状态

对于战术对局（MVP 及后续版本）：
- **对手手牌内容**：手牌中的卡牌引用列表。已知：手牌数量。未知：具体哪些牌。
- **对手牌库内容**：牌库中剩余的卡牌引用列表。已知：牌库大小。未知：哪些牌以及顺序。
- **（未来的）对手骰子颜色分布**：一个 8 维向量 `（每种骰子类型的数量）`。已知：总数量。未知：各类型的具体数量。

对于构牌模式（D11，延期）：除双方牌库构成本身隐含的信息外，无额外隐藏状态。

## CardPoolSpec 接口

对手牌库的**来源**不是硬编码的——不同的游戏模式意味着不同的对手牌库分布。采样器通过 `CardPoolSpec` 协议参数化：

```python
class CardPoolSpec(Protocol):
    def sample_opponent_deck(
        self,
        rng: Random,
        observations: Observation,
    ) -> list[int]:
        """采样一个合理的对手牌库（卡牌引用列表），
        与当前玩家迄今观察到的信息一致。"""
        ...

    def max_copies(self, card_ref: int) -> int:
        """任何合法牌库中单张卡牌允许的最大副本数。"""
        ...
```

IS-MCTS 代码只依赖这个接口。升级对手模型时，直接替换实现即可，无需修改 MCTS 代码。

### 具体实现

#### `SharedFixedPool` — MVP 实现

双方使用相同的已知卡池（当前训练模式）。对手的牌库确定性地与智能体使用相同的卡牌列表。

```python
class SharedFixedPool:
    def __init__(self, card_refs: list[int], max_copies: dict[int, int]):
        self.card_refs = card_refs
        self._max_copies = max_copies

    def sample_opponent_deck(self, rng, observations):
        # 对手的牌库就是共享卡池
        return list(self.card_refs)

    def max_copies(self, card_ref):
        return self._max_copies.get(card_ref, 2)  # 默认 2
```

当前使用此实现。对手的牌库构成是公开信息；只有当前手牌和牌库顺序是隐藏的。

#### `UniformFromPool` — 中期方案

每位玩家独立地从较大的卡池中采样构建牌库，遵守 `max_copies` 约束。对手的牌库构成本身对智能体也是未知的。

```python
class UniformFromPool:
    def __init__(self, pool_refs, deck_size, max_copies):
        self.pool_refs = pool_refs
        self.deck_size = deck_size
        self._max_copies = max_copies

    def sample_opponent_deck(self, rng, observations):
        # 受 max_copies 约束以及观察到的已打出卡牌约束
        # （已打出的牌限定了最少副本数）
        ...  # 加权采样
        return sampled_deck

    def max_copies(self, card_ref):
        return self._max_copies.get(card_ref, 2)
```

非 MVP——等到有足够大的卡池时再实现。

#### `BayesianFromPlayHistory` — 长期方案

后验推断：利用对手的观察对局历史更新其牌库构成的先验。已被打出的牌确定在其牌库中（至少 1 张）。如果某张牌明显比对手实际打出的牌更优，则是其牌库**不含**该牌的反向证据。

非常复杂；无限期延期。

## 采样流程

给定一个 `CardPoolSpec`，确定化采样器为每次 rollout 生成完整的隐藏状态：

```python
def sample_hidden_state(
    env: GicgEnv,
    viewing_player: int,
    card_pool_spec: CardPoolSpec,
    rng: Random,
) -> HiddenState:
    obs = env.export_view()
    opponent = 1 - viewing_player

    # 步骤 1：采样对手牌库构成（若未知）
    opponent_deck_pool = card_pool_spec.sample_opponent_deck(rng, obs)

    # 步骤 2：确定公开信息并减去
    # 对手弃牌堆中的牌 + 之前打出的牌已确认，
    # 必须从剩余未知池中移除
    remaining = subtract_public(opponent_deck_pool, obs, opponent)

    # 步骤 3：划分手牌和牌库
    hand_size = obs["players"][opponent]["hand_size"]
    deck_size = obs["players"][opponent]["deck_size"]
    assert hand_size + deck_size <= len(remaining)

    # 从剩余牌中随机采样手牌（均匀随机）
    hand_refs = rng.sample(remaining, hand_size)
    deck_refs = [r for r in remaining if r not in hand_refs][:deck_size]
    rng.shuffle(deck_refs)  # 牌库顺序随机

    # 步骤 4（未来骰子）：采样对手骰子颜色分布
    # MVP（AP 作为万能骰）：无需骰子采样
    # 真实骰子：从 multinomial(N, [1/8]*8) 采样 8 维向量
    # 并以本轮已公开消耗的骰子为条件
    dice_colors = None  # MVP

    return HiddenState(
        opponent_hand=hand_refs,
        opponent_deck=deck_refs,
        opponent_dice_colors=dice_colors,
    )
```

### 减去公开信息

```python
def subtract_public(deck_pool, obs, opponent):
    """从 deck_pool 中移除已公开确认的牌。"""
    # 对手弃牌堆中已公开的牌
    committed = list(obs["players"][opponent]["discard"])

    # 对手本局打出的牌（记录在事件日志中，
    # 实际上弃牌堆已包含这些牌，无需额外处理）
    # ...（若弃牌堆包含已打出的牌，则无需额外工作）

    remaining = deck_pool.copy()
    for card_ref in committed:
        if card_ref in remaining:
            remaining.remove(card_ref)
    return remaining
```

这确保采样出的对手手牌/牌库不包含已公开确认的牌。

## 将采样状态注入引擎

采样到隐藏状态后，需要将其应用到引擎，使 rollout 使用确定化后的版本：

```python
def apply_determinization(env, hidden_state, opponent):
    env.set_player_hand(opponent, hidden_state.opponent_hand)
    env.set_player_deck(opponent, hidden_state.opponent_deck)
    # 未来：env.set_player_dice(opponent, hidden_state.opponent_dice_colors)
```

**这些 setter API 尚不存在**。必须向引擎添加：
- `GameSetPlayerHand(handle, player, refs, n)`
- `GameSetPlayerDeck(handle, player, refs, n)`
- （未来）`GameSetPlayerDice(handle, player, dice_vec)`

引擎侧的工作详见 `implementation.md` Task B0。

## 带确定化的 Rollout 流程

```python
def mcts_rollout(env, root_snap, card_pool_spec, rng):
    # 1. 将 env 恢复到根节点状态
    env.restore(root_snap)

    # 2. 为本次 rollout 采样隐藏状态
    hidden = sample_hidden_state(env, viewing_player, card_pool_spec, rng)

    # 3. 注入确定化
    apply_determinization(env, hidden, opponent=1-viewing_player)

    # 4. 沿树下降，推进 env
    ...  # 标准 IS-UCT 下降

    # 5. 回溯，包括合法子节点的 N_avail
    ...
```

**注意**：每次 rollout 看到**不同的**确定化（因为每次 `restore` 推进快照的 RNG，采样器本身也使用新的随机数）。因此 MCTS 树会自动在多次确定化上累积统计数据。

## 正确性约束

1. **采样的隐藏状态必须合法**：必须满足所有观察约束（对手手牌大小、牌库大小、弃牌堆内容、已打出历史）。

2. **采样的隐藏状态必须遵守 `max_copies`**：对于任意一张牌，手牌 + 牌库 + 弃牌堆中的总数量不得超过 `card_pool_spec.max_copies(card_ref)`。

3. **采样器应无偏**：在给定观察历史的条件下，每个合理的隐藏状态应以相等的概率被采样（先验下的均匀后验）。`SharedFixedPool` 平凡地满足此条件。`UniformFromPool` 近似满足。`BayesianFromPlayHistory` 精确满足。

## 测试

采样器需要覆盖以下单元测试：
- **合法性**：采样的手牌大小与观察匹配，采样的牌在卡池中，手牌+牌库+弃牌堆中的任意牌不超过 `max_copies`
- **确定性**：给定固定种子，采样器产生可重现的输出
- **边界情况**：对手已打完所有牌（hand=0，deck=0）；对手尚未出牌（完整卡池未知）；大卡池但观察信息少
- **`SharedFixedPool` 一致性**：采样结果为完整卡池不变（因为双方共享同一牌库）

## 开放问题

- **拒绝采样 vs 直接采样**：对于 `UniformFromPool`，通过直接约束采样满足约束可能比基于拒绝的方式更高效。实现时再定。
- **部分确定化**：对于很长的游戏，随着大量卡牌被打出，"未知"集合会缩小。在某些情况下，未知集合可能小于剩余手牌 + 牌库的需求，使采样不可行。需要一个钳位规则（"若剩余牌数 ≤ 需求量，则确定性地用剩余牌填充"）。
- **骰子颜色后验**：当真实骰子系统上线后，基于对手已观察到的消耗推断骰子后验是非平凡的。MVP 使用均匀先验（每类 1/8）；未来工作通过贝叶斯更新加以细化。
