# 训练 — Reward Shaping（新卡奖励）

> 前置阅读 `docs/training/README.md`. 本文记录 reward shaping 的公式、配置
> schema 和引擎支持。

## Reward Shaping：新卡奖励

每个阶段都可以声明 `[reward_shaping]` 部分，对每局中指定"新卡"的首次打出给予奖励。
这解决了向阶段引入新卡后，智能体并不会自然去探索使用它们的问题。

```toml
[reward_shaping]
novel_cards = ["美味烧鸡", "佛跳墙", "占星", "诅咒"]
novel_bonus = 2.0
novel_bonus_decay = 0.5
novel_bonus_floor = 0.5
```

**公式**：
```
held_rounds = current_round − card.DrawnAtRound  # 0 = same-round play
bonus = max(novel_bonus − novel_bonus_decay × held_rounds, novel_bonus_floor)
```

默认值下：
- held=0（同轮打出）→ +2.0
- held=1 → +1.5
- held=2 → +1.0
- held≥3 → +0.5（地板值）

**每局去重**：`novel_cards` 中每个 `card_ref` 每局**最多触发一次**奖励。
首次成功打出后，同一 ref 的后续打出不再给予奖励。

`novel_cards` 是**独立于** `cards.cards` 的显式列表。
这一点很重要，因为部分卡牌由角色生成，永远不会出现在牌组中——
例如"复刻"是由刻师傅的刻印技能通过 `add_card` 生成的，而非从牌组摸出。
将其列入 `novel_cards` 即可在"使用刻印 → 获得复刻 → 打出复刻"的连招上给予奖励，
即使 `复刻` 从未出现在 `cards.cards` 中。

**约定**：只有**引入阶段**才在 `novel_cards` 中列出该卡。后续阶段不重复列出。
例如 phase1_warmup 列出 L2 卡牌；phase1a/b/c/d（继承自 phase1_warmup）则不再列出。
这避免了"最近学会的"策略持续吸引塑形信号。如果灾难性遗忘成为问题，
可在后续阶段的 `novel_cards` 中重新添加该卡来修正。

phase0a 是特例：它列出 `["复刻"]` 以鼓励从一开始就学习刻印连招
（即使复刻不在任何牌组中）。phase0b/c/d 不重复列出。

### 引擎支持

`CardInst` 携带一个 `DrawnAtRound int` 字段，在卡牌进入手牌时设置：

| 路径 | 创建时的 DrawnAtRound |
|------|----------------------|
| `BuildDeck`（初始牌组） | `0`（摸牌时覆写） |
| `Game.DrawCard()`（牌组 → 手牌） | `g.Round`（实际摸牌轮次） |
| `add_card` 内置函数（DSL 注入） | `g.Round` |
| `record/load.go`（replay 还原） | `0`（replay 不计算奖励） |

`Game.LastCardRef` 和 `Game.LastCardDrawnAt` 由 `executeCard` 设置，
并在每次 `Step` 入口时清除。`capi` 通过
`GameGetLastCardRef` / `GameGetLastCardDrawnAt` / `GameGetCurrentRound` /
`GameGetCardNames` 将其暴露给 Python 端的 reward shaping 逻辑。
