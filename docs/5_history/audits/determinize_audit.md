# Determinize 采样契约审计(Step 1)

Date: 2026-04-21
Scope: `training/az/determinize.py` 全实现 + 调用点

---

## 1. 数据流

```
Python 根 search 入口(training/az/mcts_go.py:225)
  ↓
  for _ in range(config.n_rollouts):
    hidden = sample_hidden_state(env, viewing_player, pool_spec, rng,
                                 opponent_dice_total=opp_dice_total)
    dets.append(_hidden_to_json(hidden, opponent))
  ↓
  Go 侧每个 rollout 取 dets[rollout_idx] 注入 engine
  ↓
  Go: applyDeterminization (gicg_mcts/rollout_helpers.go:14)
    → engine.SetPlayerHand / SetPlayerDeck / SetPlayerDice
```

**关键点**:`sample_hidden_state` 在 **root** 搜索开始时一次性采样所有
`n_rollouts` 个 determinization,前后每个 rollout 的 det 是**独立同分布**
(iid)样本,彼此无依赖关系。不会随 tree descent 变化。

---

## 2. 契约

### 2.1 `PublicObservation`(`determinize.py:29-47`)

对手的可见信息 = 查询引擎原子接口得到:
- `opponent_hand_size = engine.hand_count(opponent)` — 张数(非 refs)
- `opponent_deck_count = engine.deck_count(opponent)` — 张数
- `opponent_discard = engine.discard_refs(opponent)` — 公开的 refs 序列

**明确拒绝**:不调 `env.export_view()`(会泄露对手手牌 ref 内容)。

### 2.2 `SharedFixedPool`(唯一目前启用的 CardPoolSpec)

`sample_opponent_deck` **直接返回 `self.card_refs` 的拷贝**,**完全忽略**
`rng` 和 `observations` 两个参数:
```python
def sample_opponent_deck(self, rng, observations):
    del rng, observations  # unused: pool is fully known under MVP
    return list(self.card_refs)
```

`card_refs` 由 `training/az/pool_spec.py::resolve_pool_refs` 构建:
1. 创建一个 seed=0 的一次性 env
2. step 到 SelectActive 结束
3. 抓 `players[0]["hand"]` 的 refs
4. 补 `[filler] * deck_count` 至 hand + deck 总数
5. 返回

**⚠ 注意**:这里的 `card_refs` 有 3 个潜在问题需要后续验证:
- a) 构造时用 seed=0 的 env,若 GameReset 后 hand refs 和原 run 不同,这份 pool 就偏了
- b) "filler" 是 `refs[0]` 的重复,相当于假定所有"未见牌"都是 `hand[0]`,语义不对
- c) Pool 大小 = p0 的 (hand + deck) 总数,**不包含** p0 的 discard、p1 的 hand、p1 的 deck、p1 的 discard —— 对手 deck pool 应该独立于我方

### 2.3 `_subtract_public`(`determinize.py:120-133`)

从 pool 里 multiset-subtract 对手 discard 的每张。不找到不报错(silent 忽略)。

### 2.4 `sample_hidden_state` 主流程(`determinize.py:153-212`)

```python
pool = card_pool_spec.sample_opponent_deck(rng, pub)   # ← SharedFixedPool 下 = self.card_refs
remaining = _subtract_public(pool, pub.opponent_discard)

needed = hand_size + deck_size
if needed > len(remaining):
    # 降级:hand 优先,deck 截断
    ...

chosen = rng.sample(remaining, needed)   # 无放回均匀采样
hand_refs = chosen[:hand_size]
deck_refs = chosen[hand_size:hand_size + deck_size]
rng.shuffle(deck_refs)
```

**采样分布**:从 `remaining`(= `card_refs` - `opponent_discard`)里**无放回均匀**
抽 `hand_size + deck_size` 张。前 `hand_size` 做对手 hand,后面做 deck 并 shuffle。

### 2.5 `sample_opponent_dice`(`determinize.py:95-117`)

对手骰子:`np.random.multinomial(total_count, [1/8]*8)` 一次独立 multinomial 抽样。
**均匀先验,无后验更新**(文档承认是 "no information" 版本)。

---

## 3. 契约硬不变量(可做 Step 2 测试)

### MUST HOLD(如果实现正确)

| # | 断言 | 违反意味着 |
|---|---|---|
| I1 | `len(hidden.opponent_hand) == hand_size` | 计数 bug |
| I2 | `len(hidden.opponent_deck) == deck_size` | 计数 bug |
| I3 | 所有 hand/deck refs ∈ `remaining`(= pool - opponent_discard) | 采样没过滤 |
| I4 | `set(hand) ∪ set(deck)` 各个 ref 的 multiset 计数 ≤ remaining 的 multiset 计数 | 无放回违反 |
| I5 | `sum(dice_colors) == opponent_dice_total` | multinomial 契约 |
| I6 | `all(c >= 0 for c in dice_colors)` | multinomial 契约 |
| I7 | 不同 seed 的 rng 产出不同 hidden(除 hand_size=0 极端) | 采样器失效 |

### 已知故意放宽(MVP 约束)

- **Degenerate clamp**:若 `needed > len(remaining)`,hand 优先 deck 截断。
  SharedFixedPool 下理论上触发不了,但代码保留 fallback。
- **Opponent dice uniform prior**:没有用"对手之前已支付 dice color"做贝叶斯后验更新。

---

## 4. 已发现的设计缺陷(不算 bug 但可能有实际影响)

### D1: SharedFixedPool 的 pool 构造有漏洞

`resolve_pool_refs` 的 pool = **p0 的 (hand + filler * deck_count)**。

问题链:
1. 用 seed=0 env,其中 p0 初始 hand 和 deck **随机洗牌后的 ref 序列** 就是这个 pool
2. 填充 filler = `hand[0]`,deck_count 个同一个 ref 填入 pool
3. pool 不代表"真实 card_pool 多重集",只是 "一次实验里 p0 看到的 hand 序列 + 一个 ref 的重复"

换句话说:**pool 里的 ref 多重集分布 ≠ 真实 pool**。

对 SharedFixedPool 的理论正确性要求"pool = 对手 deck 的已知构成",当前实现**做不到**。

**对训练的实际影响**:
- 对手 hand 采样偏差:倾向于采到 p0 初始 hand 里的 ref,混上大量 filler
- 若 card_pool scenario 是"同一种 deck"(r001-r005 场景),偏差相对小
- 若 card_pool 有多种 card type 分布不均,偏差大

### D2: Dice 是 uniform 8-color,无 Bayesian 更新

`sample_opponent_dice` 假定对手 dice 服从 8 色均匀 multinomial。
实际上:
- 对手**初始 roll** 是均匀 8 色,这是对的
- 对手**支付过的 dice**(public:从 discard 可推断 payment → 哪些 color 减少了)未被更新
- 对手**剩余 dice** 的后验应该 = 初始 - 已支付

当前实现:直接从 `total_count` 开始均匀采,**忽略**了支付历史。

**对训练的实际影响**:
- 对手 dice 估计偏向均匀,实际后验可能更尖(已知支付了 3 fire → 剩余 fire 概率低)
- MCTS 搜索对手行动时,假设对手 dice 分布比真实更"温和" → 策略可能过度乐观估计对手反击能力

### D3: deck ordering 完全随机 shuffle

```python
deck_refs = chosen[hand_size:hand_size + deck_size]
rng.shuffle(deck_refs)
```

对手 deck 内部完全随机排序。这个**对 IS-MCTS 正确**,因为对手下一轮会抽哪张牌确实是不可观察的未来。**不是 bug**。

### D4: `root_value_p0` 的"对手 dice 总数"

```python
opp_dice_total = env._engine.dice_total(opponent)
```

使用 **当前** engine 的对手 dice count。但调用 `sample_hidden_state` 前,engine 状态是
`viewing_player` 的视角,对手 dice count 是**公开**的(总数,非分布)—— 这一步契约正确。

---

## 5. Step 2 测试目标

按不变量 I1-I7 写 `training/tests/test_determinize_posterior.py`:
1. 构造一个 SharedFixedPool 局面,采 N=1000 det
2. 验证每个 hidden 满足 I1-I7
3. 聚合:每个 ref 在 hand 里出现的频率 → 理论频率 = (ref 在 remaining 的 count) /
   len(remaining) × hand_size / (hand + deck)
4. 卡方检验 or 相对误差阈值

Step 2 不变量测试发现的 bug 类型:
- I1/I2 违反 → 计数逻辑 bug
- I3/I4 违反 → 采样没过滤 discard
- I5/I6 违反 → numpy multinomial 调用错误

Step 2 分布测试能发现的偏差:
- D1 的影响实际有多大(看多重集命中率)
- hand/deck 切分是否真的均匀

---

## 6. 结论与推荐

### 关键发现

1. **实现是正确的**(按 MVP 契约无 bug)——所有 I1-I7 应都成立
2. **设计是粗糙的**:
   - D1(pool 构造只用 p0 hand + filler)= 实际影响待测,对同质 deck 场景小
   - D2(dice uniform)= 确定性偏差,但理论上对两边对称,不造成系统性劣势
3. **D1/D2 都是可以改进的设计选择**,不影响 IS-MCTS 算法正确性,只影响采样分布的**信息量**

### 和 r003/r004/r005A 结果的关系

- **D1 漏出的主因不是 determinize 采样分布**,而是 K=3 union 只变 dice 维不变 hand 维
- r001-r005A 都用同一个 determinize 实现,所以它作为**common factor** 不能解释 run 间的差异(r001 0.55 vs r002 0.30)
- determinize 的粗糙会让**所有 run 同等变弱**,不影响相对对比

### Step 2 优先级

建议仍跑 Step 2 invariant test,**重点验证 I3 和 I4**(hand/deck refs 合法性)。若 I3/I4 失败,就是硬 bug,会系统性污染所有 run。

如果所有 invariant pass,D1/D2 的"分布偏差"是 Tier 3 的设计改进空间,不算 blocker。
