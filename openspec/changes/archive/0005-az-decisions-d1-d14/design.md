# Design (retrospective)

## Consequences

### 证据摘要(决策依据)

- Snapshot 原语基准:`snapshot/restore` 约 8 µs,对游戏规模 O(1)。Python MCTS 100-300 局/小时/进程,
  4 进程 1-2.8 万局/天,远超 PPO 1600 局/天
- MCTS vs 策略实战:3 场景 120 局 = MCTS 117 / 策略 3;2v2 L1+L2 完全封杀(phase1b 失败场景)

### 决策保留 / 重构 / 废弃

**保留**:`gicg_engine/`、`data/`、`gicg_engine/record/`、`web/`、`gicg_env/engine.py`、
`Game.snapshot/restore/clone`

**重构**:`gicg_env/env.py::GicgEnv` (去 reward shaping,签名 `(obs, done, info)`,移除新卡追踪);
`training/az/network/actor_critic.py::ActorCritic` (保留 encoder + cross-attn,策略采样换访问计数 CE,
价值 GAE 换结果 MSE,移除 per-env 缓存);`CardEncoder` / `CharEncoder` 扩展消费特征向量;observation
layout (已在 `observation.go:309-393` 正确处理视角,无需变更)

**废弃**:`training/ppo.py` / `training/rollout.py` / `training/selfplay.py` / `training/stage_loop.py`
/ `training/opponent_pool.py` / `training/reward_norm.py`;PPO 专用测试;`configs/curriculum/` /
`configs/stages/phase*.toml`;注意力诊断 hook(若有)

### 计划阶段

| 阶段 | 目的 | 时长 |
|---|---|---|
| B | 核心训练栈 (B0-B7) | 约 7.5 天 |
| C | MVP 场景验证 (C1-C4) | 约 3-5 天 |
| D | PPO 栈清理 (D1-D4) | 约 2-3 天 (延后) |
| E | 扩展功能 (骰子 / 角色 / 构牌) | 未来 |

**总时长 12.5-15.5 天 + cleanup**。

## Tradeoffs revisited

### D6 升级方案触发情况

bootstrap 监控指标:含至少一个"连携关键"决策(MCTS Q 跳跃 > 0.3,策略先验较低,且获胜)的游戏滚动
比例。若多窗口持续为 0 → bootstrap 停滞。

升级方案(响应式,默认关闭):
1. 提高 Dirichlet 噪声(`alpha=0.5, eps=0.4`)
2. 启用 D13 模式 B(发现时扩展搜索)
3. 临时使用启发式 rollout 策略进行叶节点评估
4. 注入 5-20 条手工编写的连携示例作为监督数据

后续 ADR-0008 反 evidence(r001-r008 全失败)直接接受了 "rollout 比 net-value 强 10×" 的 C1v2 结论;
本 ADR 的 D5 纯终局 / D6 纯 random init 也在 ADR-0008 中被显式重评估。

### D7 实际落地范围

骰子相关设计原稿(8 类骰子、三种费用原子与结构、切换/调音费用)仍保留在 `dice_spec.md`,但**实际
shipped 行为的权威来源是代码**(`gicg_engine/interp/dice.go` / `cost_payment.go` / 对应 capi exports)。

完整骰子规格(MVP 后实现):7 种元素骰子 + 1 种万能 = 8 种;每局每轮投掷 8 颗,各 1/8;轮末丢弃;
3 种费用原子(n 同色 / n 无色 / n 特定色);3 种结构(纯同色 / 纯无色 / 特定色+无色);切换费用 1
无色无每轮限制;调律 = 1 牌 + 0 骰;全万能满足同色;**支付时骰子选择是战略动作**,编码为联合复合
动作(非子动作)。

### D14 ExpandUnionK 被实证否决(2026-04-21)

**Deprecated 2026-04-21 in-text** — `29ca0c4` 全量移除。根因:r005A 事后消融实测 K=3 vs_mcts_200
0.45→0.40 净负 0.05;policy loss 改善但 argmax 胜率反向相关(登记在 registry)。

事后诊断:ExpandUnionK 只在 **dice 维**枚举 union,不在 **hand/deck** 维扩展。D1 新动作覆盖率埋点
显示当前实现只涵盖 **<20%** 的 D1 触发场景 — 大部分新动作源自 card draw + play 隐藏状态,不是 dice。
K=3 增加 MCTS 计算成本 + 增加 π_target 形状扭曲,但不解决它本应解决的 D1 问题。

代价:D1 问题未解决,由后续 A1 方案(D1 actions network-informed prior)接手;A1 单独 scope,不复用
ExpandUnionK 代码。

## 待解问题 / 延后议题

- 卡牌/角色特征提取:DSL 中具体特征 / MLP 还是注意力块。MVP 用朴素特征 + 2 层 MLP,根据 ablation
  迭代
- `max_copies` 字段语法:逐卡设置 + 全局默认
- 竞技场评估频率 + 替换阈值:默认 `每 500 局 > 55%`,在 C 阶段调优
- 并行自对弈 worker 数:取决于硬件
- Dirichlet 噪声参数:默认 `alpha=0.3, eps=0.25`
- 大卡池确定化采样器 (`UniformFromPool`):非 MVP

## References

- `docs/2_decisions/adr-0005-az_decisions_d1_d14.md` (mirror)
- `../0008-rl-paradigm-pivot/` — 部分修正 D5 / D6
- `../0004-is-mcts-migration/` — D1 (Python → Go) 修正路径
- `docs/5_history/decisions_legacy/` 原 az 顶层决策展开:`mcts_design.md` / `network_design.md` /
  `dice_spec.md` / `training_loop.md` / `determinization.md` / `implementation.md`
- `docs/5_history/az/evidence/` — bench_snapshot.md / mcts_vs_policy.md
- `docs/5_history/ablations/r001_r006_ablation.md` — D14 配套 ablation 总结
- memory `project_expand_union_k` — D14 OBSOLETE 实证
- `gicg_engine/interp/dice.go` + `cost_payment.go` — D7 shipped
- `training/az/config.py::ScenarioConfig` — D10 shipped
