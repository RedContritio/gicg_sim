# 训练计划（已废弃）

> **⚠️ 已于 2026-04-14 废弃。** 本目录描述的是
> **PPO 时代**的训练栈（课程、pool ELO、reward shaping、
> 阶段门控），正在被 [`docs/current/az/`](../../../current/az/README.md) 中记录的
> AlphaZero + IS-MCTS 框架所取代。
>
> PPO 栈在以下情况后退役：(a) `phase1b` 在优化后的栈（B3 + C + 最小奖励）下
> 陷入持续退化，以及 (b) 可行性探测显示纯 MCTS 在三个场景下以 117-3 击败
> 训练好的 phase1a 检查点。迁移理由参见
> [`docs/current/az/decisions.md`](../../../current/az/decisions.md)，数据参见
> [`docs/history/az/evidence/`](../../../history/az/evidence/)。
>
> 以下内容仅保留供历史参考。

---

> 最后修订于 2026-04-13，更新内容：镜像对战 bug 修复，引入 dropout + reward shaping。
> 本文取代早期硬编码 selfplay.train() 时代的计划。

## 课程结构

6 个 phase × （4 个子阶段 + 1 个预热）= **29 个阶段**。phase0 没有预热，
因为它是引导阶段。

| Phase | 新引入卡牌 | 子阶段 | 预热 |
|-------|------------|--------|------|
| phase0 | （仅填充：碌碌无为） | a, b, c, d | — |
| phase1 | + L2 卡牌 | a, b, c, d | phase1_warmup |
| phase2 | + L3 卡牌 | a, b, c, d | phase2_warmup |
| phase3 | + L4 卡牌 | a, b, c, d | phase3_warmup |
| phase4 | + L5 卡牌 | a, b, c, d | phase4_warmup |
| phase5 | + L6 卡牌 | a, b, c, d | phase5_warmup |

**子阶段队伍规则**（各 phase 一致）：

| 子阶段 | 队伍规则 | 目标 |
|--------|---------|------|
| a | 镜像 1v1（相同单角色） | 单角色技能/卡牌掌握 |
| b | 非镜像 1v1 | 角色对战适应性 |
| c | 镜像 NvN，N∈[1,3] | 切换 / 多角色协调 |
| d | 非镜像 NvN，N∈[1,3] | 完整决策能力 |

**角色池**：从 phase0 起使用全部 5 个角色 `["赤蝶","墨客","猫咪","刻师傅","天星"]`。角色课程不设门控。

## 卡池进展

卡牌在每个阶段的 `[cards]` 部分**按名称明确列出**。
阶段**不从** `data/cards/L*` 目录布局**推断**卡池——
L1-L6 文件夹结构仅供人工组织使用。

无论卡池内容如何，运行时总会加载填充卡 `碌碌无为`
（BuildDeck 用它填充短牌组）。

每个子阶段的 `[cards]` 使用 `extends_path` 继承自前一阶段，并在此基础上添加新卡：

```toml
# phase1_warmup.toml
[cards]
mode = "explicit"
extends = "../stages/phase0d.toml"
cards = ["美味烧鸡", "佛跳墙", "占星", "诅咒"]   # new L2 cards on top of phase0d
```

同一 phase 内的 a/b/c/d 子阶段通过
`extends = "../stages/phase{N}_warmup.toml"` 共享预热阶段的完整卡池（无需重新列举）。

## 对手模式

| 阶段 | 训练对手 | 评估对手 | 原因 |
|------|----------|----------|------|
| phase0a | random | random | 引导阶段，无 prior 可对比 |
| phase0b/c/d | mix | prior | 标准自博弈 vs prior 链 |
| phase{N≥1}_warmup | random | random | 自由探索新引入的卡牌 |
| phase{N≥1}a/b/c/d | mix | prior | 自博弈 vs prior，prior = 上一个通过阶段的检查点 |

模式（对应 `training/selfplay.py` 中 `VectorizedRollout` 的模式常量）：
- `self` → `MODE_SELF` — 智能体对战自身，双方均记录。
- `random` → `MODE_VS_RANDOM` — 对手从合法动作中均匀随机选择。
- `prior` → `MODE_VS_AGENT` — 对手为最近通过阶段的检查点（冻结）。
- `mix` → `MODE_MIX` — 每局在自博弈和 vs-prior 之间交替
  （每批中一半为自博弈，另一半为 vs-prior）。
- `hybrid_prior0` → `MODE_HYBRID_PRIOR0` — 对手仅在主动角色为 0 号槽时使用 prior 检查点；其他槽位随机行动。用于打破镜像 NvN 阶段的对称策略陷阱。
- `pool` → `MODE_POOL` — 对手每局从 AlphaStar 风格的历史检查点池（`training/opponent_pool.py`）中采样。采样权重为基于当前智能体 ELO 接近度的 softmax 加权。与 `[progression] pass_elo_delta = X` 配合使用时，将阶段的晋级门限从胜率切换为 ELO delta（参见 `docs/training/promotion.md`）。

`prior` / `mix` / `hybrid_prior0` 至少需要一个通过的检查点；
`pool` 需要 `ctx.pool` 非空。在运行的首个阶段使用以上任意模式
会在阶段入口抛出 `RuntimeError`。


---

## 参见

- `docs/training/reward_shaping.md` — 新卡奖励公式及引擎支持
- `docs/training/promotion.md` — A 方案（连续评估）+ G 方案（部分通过）晋级逻辑
- `docs/training/hparams.md` — 网络/PPO/训练 cadence 超参，产物路径约定，ELO 长期方向
- `docs/decisions/engine_bugs.md` — 解锁镜像对战训练的 bug 修复
- `docs/decisions/training_design.md` — 本课程重设计的完整 ADR
- `docs/training/legacy/` — 前 Go 引擎时代的历史/已废弃训练计划；保留供考古，不代表当前规范
