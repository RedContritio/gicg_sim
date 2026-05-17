---
last_updated: 2026-05-15
status: LIVE
schema_version: 0
capability: search-ismcts
subtopic: determinization
---

# Determinization — CardPoolSpec / 隐藏状态采样 / 引擎注入 / rollout 流程

> 本 subtopic 锚定 GICG IS-MCTS 的确定化采样器规约 — `CardPoolSpec`
> 接口契约、隐藏状态采样流程(对手手牌 + 牌库 + 未来骰子)、公开
> 信息减去、注入引擎的 setter API、完整 rollout 流程。算法本体见
> [`./algorithm.md`](./algorithm.md);树结构见 [`./tree-structure.md`](./tree-structure.md)。

## 1. CardPoolSpec 接口

IS-MCTS 需要从智能体看不到对手隐藏信息的状态出发向前模拟。**确定化**
= 在每次 rollout 时采样一个合理的具体隐藏状态,在该采样状态上运行模拟,
对多次采样汇总。Cowling 2012(IS-UCT)在每次 rollout 开始时从共享树
根节点执行确定化,**不**通过独立 MCTS 树。

### 1.1 SHALL invariants

1. Determinization SHALL be parameterized by a `CardPoolSpec` protocol
   — IS-MCTS 代码 SHALL NOT depend on a specific card pool 实现:

   ```python
   class CardPoolSpec(Protocol):
       def sample_opponent_deck(
           self,
           rng: Random,
           observations: Observation,
       ) -> list[int]:
           """采样一个合理的对手牌库(卡牌引用列表),
           与当前玩家迄今观察到的信息一致。"""
           ...

       def max_copies(self, card_ref: int) -> int:
           """任何合法牌库中单张卡牌允许的最大副本数。"""
           ...
   ```

2. 升级对手模型时 SHALL replace `CardPoolSpec` implementation 而非
   修改 MCTS 代码。
3. 当前 shipped SHALL use `SharedFixedPool`(共享卡池 MVP);中长期
   升级路径(`UniformFromPool` / `BayesianFromPlayHistory`)见 §1.2。

### 1.2 三个 CardPoolSpec 实现

#### `SharedFixedPool`(MVP shipped)

双方使用相同的已知卡池(当前训练模式)。对手的牌库构成是公开信息;
只有当前手牌和牌库顺序是隐藏的。

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

#### `UniformFromPool`(中期方案,未 shipped)

每位玩家独立地从较大的卡池中采样构建牌库,遵守 `max_copies` 约束。
对手的牌库构成本身对智能体也未知。

```python
class UniformFromPool:
    def __init__(self, pool_refs, deck_size, max_copies):
        self.pool_refs = pool_refs
        self.deck_size = deck_size
        self._max_copies = max_copies

    def sample_opponent_deck(self, rng, observations):
        # 受 max_copies 约束 + 已打出卡牌约束(已打牌限定最少副本数)
        ...  # 加权采样
        return sampled_deck
```

#### `BayesianFromPlayHistory`(长期方案,未 shipped)

后验推断:利用对手观察对局历史更新其牌库构成先验。已被打出的牌确定
在其牌库中(至少 1 张)。若某牌明显比对手实际打出的牌更优,则是其
牌库**不含**该牌的反向证据。复杂度高,无限期延期。

### 1.3 构牌模式(D11,延期)

除双方牌库构成本身隐含信息外,无额外隐藏状态。本 spec 当前不展开
deckbuild 模式;若 D11 reopen,SHALL 通过 OpenSpec change 扩展本
subtopic。

## 2. 隐藏状态采样流程

### 2.1 需要采样的隐藏状态(战术对局)

- **对手手牌内容**:手牌中的卡牌引用列表。已知:手牌数量。未知:具体哪些牌。
- **对手牌库内容**:牌库中剩余的卡牌引用列表。已知:牌库大小。未知:哪些牌以及顺序。
- **(未来)对手骰子颜色分布**:8 维向量(每种骰子类型数量)。已知:总数量。未知:各类型具体数量。

### 2.2 SHALL invariants

1. `sample_hidden_state(env, viewing_player, card_pool_spec, rng)` SHALL
   produce a `HiddenState` containing:
   - `opponent_hand`(list of card refs,长度 = 观察到的对手手牌数)
   - `opponent_deck`(list of card refs,长度 = 观察到的对手牌库大小)
   - `opponent_dice_colors`(future,MVP 阶段 `None`)

2. 流程 SHALL be:
   - **Step 1**:`opponent_deck_pool = card_pool_spec.sample_opponent_deck(rng, obs)`
   - **Step 2**:`remaining = subtract_public(opponent_deck_pool, obs, opponent)` — 减去已公开的牌(对手弃牌堆 + 已打出的牌)
   - **Step 3**:`assert hand_size + deck_size <= len(remaining)`;`rng.sample(remaining, hand_size)` 抽手牌,剩下 `deck_size` 张作牌库,`rng.shuffle(deck_refs)` 打乱顺序
   - **Step 4**(future dice):从 `multinomial(N, [1/8]*8)` 采样 8 维向量,以本轮已公开消耗骰子为条件;MVP `dice_colors = None`

3. `subtract_public` SHALL remove:
   - 对手弃牌堆中已公开的牌(从 obs)
   - 对手本局打出的牌(若弃牌堆已含则无需额外处理)

   ```python
   def subtract_public(deck_pool, obs, opponent):
       committed = list(obs["players"][opponent]["discard"])
       remaining = deck_pool.copy()
       for card_ref in committed:
           if card_ref in remaining:
               remaining.remove(card_ref)
       return remaining
   ```

4. 采样器 SHALL be **deterministic given (rng, obs, card_pool_spec)** —
   固定 seed 产生可重现输出(供测试 + 调试)。

### 2.3 完整伪代码

```python
def sample_hidden_state(
    env: GicgEnv,
    viewing_player: int,
    card_pool_spec: CardPoolSpec,
    rng: Random,
) -> HiddenState:
    obs = env.export_view()
    opponent = 1 - viewing_player

    opponent_deck_pool = card_pool_spec.sample_opponent_deck(rng, obs)
    remaining = subtract_public(opponent_deck_pool, obs, opponent)

    hand_size = obs["players"][opponent]["hand_size"]
    deck_size = obs["players"][opponent]["deck_size"]
    assert hand_size + deck_size <= len(remaining)

    hand_refs = rng.sample(remaining, hand_size)
    deck_refs = [r for r in remaining if r not in hand_refs][:deck_size]
    rng.shuffle(deck_refs)

    dice_colors = None  # MVP

    return HiddenState(
        opponent_hand=hand_refs,
        opponent_deck=deck_refs,
        opponent_dice_colors=dice_colors,
    )
```

## 3. 将采样状态注入引擎

### 3.1 SHALL invariants

1. After sampling hidden state, IS-MCTS SHALL inject via engine setter
   API(每次 rollout 开始):

   ```python
   def apply_determinization(env, hidden_state, opponent):
       env.set_player_hand(opponent, hidden_state.opponent_hand)
       env.set_player_deck(opponent, hidden_state.opponent_deck)
       # 未来:env.set_player_dice(opponent, hidden_state.opponent_dice_colors)
   ```

2. Required engine APIs(由 [`engine-dsl`](../engine-dsl/spec.md)
   capability 治理):
   - `GameSetPlayerHand(handle, player, refs, n)`
   - `GameSetPlayerDeck(handle, player, refs, n)`
   - (future)`GameSetPlayerDice(handle, player, dice_vec)`

3. Setter API SHALL be invoked AFTER `env.restore(root_snap)` and
   BEFORE tree descent — 顺序确保每次 rollout 用新的确定化,而非沿用
   上一次的。

### 3.2 完整 rollout 流程

```python
def mcts_rollout(env, root_snap, card_pool_spec, rng):
    # 1. 恢复 env 到根节点状态
    env.restore(root_snap)

    # 2. 为本次 rollout 采样隐藏状态
    hidden = sample_hidden_state(env, viewing_player, card_pool_spec, rng)

    # 3. 注入确定化
    apply_determinization(env, hidden, opponent=1-viewing_player)

    # 4. 沿树下降,推进 env(IS-UCT 选择 + 扩展,见 ./algorithm.md)
    ...

    # 5. 回溯,包括合法子节点的 N_avail(见 ./algorithm.md §4)
    ...
```

**注意**:每次 rollout 看到**不同的**确定化(因 `restore` 推进
snapshot RNG + 采样器本身用新随机数)。MCTS 树自动在多次确定化上累积
统计数据。

## 4. 正确性约束

### 4.1 SHALL invariants

1. **合法性**:采样的隐藏状态 SHALL satisfy all observation constraints
   — 对手手牌大小 / 牌库大小 / 弃牌堆内容 / 已打出历史。
2. **`max_copies` 遵守**:对任意一张牌,采样的 `hand + deck + discard`
   总数量 SHALL NOT exceed `card_pool_spec.max_copies(card_ref)`。
3. **采样器无偏**:在给定观察历史的条件下,每个合理的隐藏状态 SHOULD
   be sampled with equal probability(先验下的均匀后验)。
   `SharedFixedPool` 平凡满足。`UniformFromPool` 近似满足。
   `BayesianFromPlayHistory` 精确满足。

## 5. 测试覆盖

确定化采样器 SHALL have unit tests covering:

- **合法性**:采样手牌大小与观察匹配,采样牌在卡池中,`hand + deck +
  discard` 中任意牌不超过 `max_copies`
- **确定性**:给定固定 seed,采样器输出可重现
- **边界情况**:对手已打完所有牌(`hand=0, deck=0`);对手尚未出牌
  (完整卡池未知);大卡池但观察信息少
- **`SharedFixedPool` 一致性**:采样结果为完整卡池不变(双方共享同一
  牌库)

## 6. 开放问题

以下为 implementation 决策点,非 SHALL 锁定项:

- **拒绝采样 vs 直接采样**:对于 `UniformFromPool`,通过直接约束采样
  满足约束可能比基于拒绝的方式更高效。实现时再定。
- **部分确定化**:长游戏随大量卡牌被打出,"未知"集合会缩小。某些情况
  下未知集合可能小于剩余手牌 + 牌库的需求,使采样不可行。需钳位规则
  ("若剩余牌数 ≤ 需求量,则确定性地用剩余牌填充")。
- **骰子颜色后验**:真实骰子系统上线后,基于对手已观察消耗推断骰子
  后验非平凡。MVP 用均匀先验(每类 1/8);未来工作通过贝叶斯更新加以
  细化。

## 7. Cross-references

- [`./algorithm.md`](./algorithm.md) — IS-UCT 算法本体(本 subtopic
  的采样器在 §7 `mcts_search` 伪代码中调用)
- [`./tree-structure.md`](./tree-structure.md) §5 — 快照/恢复原语
  (本 subtopic 的 rollout 流程依赖 `env.snapshot` / `env.restore`)
- [`../engine-dsl/spec.md`](../engine-dsl/spec.md) — `GameSetPlayerHand` /
  `GameSetPlayerDeck` setter API 契约
- ADR-0005 D9 `CardPoolSpec` 接口决策(`openspec/changes/archive/
  0005-az-decisions-d1-d14/`)
