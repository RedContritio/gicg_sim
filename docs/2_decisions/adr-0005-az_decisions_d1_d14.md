# IS-MCTS + AlphaZero 迁移 — 决策日志

> **MOVED to `openspec/changes/archive/0005-az-decisions-d1-d14/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0005-az-decisions-d1-d14/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


> 这是**顶层决策日志**。各决策的实现细节请参阅对应的专题文档：
>
> - 算法、网络、骰子、训练与确定化设计 → [归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)
> - 任务待办 / 代码布局 → [归档任务](../../openspec/changes/archive/0005-az-decisions-d1-d14/tasks.md)
> - 迁移的证据 → [`docs/5_history/evidence/`](../5_history/evidence/)

## 背景

**截至 2026-04-14**，项目运行基于 per-size-pool ELO 门控课程（phase0-5）的 PPO 自对弈。我们连续快速落地了三项改进——B3 运行奖励归一化、C per-size pool ELO，以及最小奖励（14 → 3 个系数）。在组合栈下的首次训练运行（`202604141523_p0p1_minrew`）干净通过了 phase0a 至 phase1a，但 **phase1b 在约第 150 轮迭代附近陷入持续回归**，Δ 在第 170 轮跌至 -289，停止训练时仍维持在约 -238。各项单独指标（`val_ret_corr`、`v_loss`、`clip_frac`）均健康，但策略无法恢复。

一次可行性探测使方向无法辩护：**一个 200 次 rollout 的纯随机 rollout UCT 玩家在三个场景下以 117-3 击败了经过训练的 phase1a 策略**（1v1 L1、1v1 L1+L2、2v2 L1+L2——每种 40 局，交替先手）。完整结果见
[`evidence/mcts_vs_policy.md`](../5_history/evidence/mcts_vs_policy.md)。

本文档记录了 2026-04-14 做出的从 PPO 迁移到 AlphaZero 风格 MCTS + 神经网络协同训练的决策，并使用信息集 MCTS（IS-MCTS）处理不完美信息。

---

## 证据摘要

- **快照原语基准测试**
  ([`evidence/bench_snapshot.md`](../5_history/evidence/bench_snapshot.md))：
  `snapshot` / `restore` 约 8 µs，且**对游戏规模为 O(1)**。
  单进程 Python MCTS 吞吐量为 100–300 局/小时；
  4 进程 CPU 并行可达 1–2.8 万局/天，远超
  PPO rollout 的约 1600 局/天。

- **MCTS 对比策略的实战测试**
  ([`evidence/mcts_vs_policy.md`](../5_history/evidence/mcts_vs_policy.md))：
  三个场景共 120 局，**MCTS 117 胜，策略 3 胜**。
  2v2 L1+L2 完全封杀——正是 phase1b 失败的场景。
  纯搜索、无任何学习组件，便能主导 1500 轮 PPO 训练。

**结论**：基于搜索的方法具有绝对优势。PPO 栈在架构上与两人不完美信息零和博弈不匹配。"阶段过渡崩溃"（phase0c→d、phase1a→b）是单智能体 PPO 在不断变化的游戏设置下无法维持稳定自对弈均衡的症状。

---

## 决策

### D1：MCTS 在 Python 中实现，而非 Go

**问题**：MCTS 树代码实现在何处。

**选项**：(A) Python——迭代快，有 ctypes 开销；
(B) Go——更快，但树结构和网络 IPC 的工程成本高得多。

**决策**：A。基准测试显示 100–300 局/小时/进程，
4 核并行超过 PPO 吞吐量。仅在 profiling 确认 ctypes 边界是实际瓶颈时才迁移到 Go。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D2：信息集 MCTS，单棵树，IS-UCT 配合 N_avail

**问题**：MCTS 如何处理不完美信息（对手手牌、牌库顺序、未来骰子、未来抽牌）。

**选项**：(A) PIMC 配完美信息偏差；(B) 根节点确定化 K 路搜索；(C) **IS-UCT 单棵树**，每次 rollout 确定化，并维护 `N_avail` 簿记。

**决策**：C——Cowling 等人 2012 年的单棵树 IS-UCT。
智能体自身的动作在各次确定化中合法性稳定，简化了实现——只有对手节点需要处理合法性过滤。

**参考文献**：Cowling, Powley, Whitehouse (2012)。"Information
Set Monte Carlo Tree Search." IEEE Trans. on CIAIG.

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D3：单一网络，共享主干，共享价值头，各阶段独立策略头

**问题**：网络如何与两个游戏阶段（战术对战、未来构牌）对应。

**选项**：(A) 独立网络；(B) **共享主干 + 共享价值头 + 各阶段独立策略头**；(C) 横跨两个阶段的单棵 MCTS 树（分支因子问题）。

**决策**：B。价值头是跨阶段的桥梁——它从多样化的战术训练中学习"预期游戏结果"，并在查询时直接提供给构牌阶段。无需显式的"元知识迁移"。

**MVP 约束**：网络架构必须为未来添加 `deckbuild_policy_head` 留有空间，而无需重构主干。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D4：无对手池，始终与当前网络自对弈

**问题**：AZ 是否需要像 PPO 那样的历史检查点池？

**决策**：不需要。自对弈始终对双方使用同一个网络。
多样性来自 MCTS 探索（根节点 Dirichlet 噪声 + 温度计划），而非池的异质性。竞技场评估保留用于检查点替换决策。

**已废弃**：`training/opponent_pool.py`、per-size ELO 重构、
哨兵锚点逻辑、所有阶段配置中的 `opponent = "pool"` 引用。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D5：纯终局奖励 ±1，无奖励塑形

**决策**：奖励为胜利 `+1`、失败 `-1`、平局 `0`，
所有中间步骤为 0。价值头仅从胜利信号学习工具性价值（伤害、站位、护盾）——这是标准 AZ 做法。

**已废弃**：`_compute_reward_from_events`、`RewardCoefs`、
新卡追踪、每步奖励管道。`GicgEnv.step` 签名变为 `(obs, done, info)`。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D6：纯 AlphaZero，随机初始化，配合 bootstrap 监控

**问题**：是否应从 MCTS 监督数据热启动网络？以及：GICG 的连携机制（调律 → 切换 → 打出 → 击杀序列，每局不到 1 次）是否会导致随机初始化 AZ 的 bootstrap 失败？

**决策**：从随机初始化的纯 AlphaZero 开始，**配合主动的连携发现指标**和**若 bootstrap 停滞则启动的应急升级方案**。

**监控**：包含至少一个"连携关键"决策（MCTS Q 跳跃 > 0.3、策略先验较低、且游戏获胜）的游戏的滚动比例。若该比例在多个窗口内持续为 0，则 bootstrap 已停滞。

**升级方案（响应式，默认关闭）**：
1. 提高 Dirichlet 噪声（`alpha=0.5, eps=0.4`）
2. 启用 D13 模式 B（在发现时扩展搜索）
3. 临时使用启发式 rollout 策略进行叶节点评估
4. 注入 5-20 条手工编写的连携示例作为监督数据

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D7：骰子机制（MVP 起步时延后，现已实现）

**问题**：骰子机制会增加引擎状态、新的不完美信息、新的动作合法性规则以及围绕骰子消耗的策略选择。MVP 是否应该实现它？

**原始决策（2026-04-14）**：MVP 中不实现骰子机制，AP 视为"万能骰"。

**实际落地**：骰子系统已在 AZ step 前后完成端到端实现。shipped 组件：
- 引擎侧：`gicg_engine/interp/dice.go`（骰子池 counter 与元素映射）、
  `gicg_engine/cost_payment.go`（支付求解）、
  `Ruleset.BuildDiceIndex`（行动到支付枚举的索引）、
  `GameSetPlayerDice` capi（确定化注入）
- Python 侧：`training/az/determinize.py` 中骰子颜色采样；
  `training/az/network/actor_critic.py` 的 `dice_combo_proj` 将 8 维 payment 向量投影到
  行动特征；`training/az/mcts/` 通过 `action_payments` 驱动叶节点 eval
- 测试：`gicg_engine/tests/dice_test.go`

骰子相关的设计原稿（8 类骰子、三种费用原子与结构、切换/调音费用）
仍保留在 `dice_spec.md` 中作为概念参考，但**实际 shipped 行为的权威来源
是代码**（`gicg_engine/interp/dice.go`、`cost_payment.go` 与对应 capi 导出）。

**完整骰子规格**（用于 MVP 后实现）：7 种元素骰子类型 + 1 种万能骰 = 8 种；每局每轮投掷 8 颗，各 1/8 概率；轮末丢弃；3 种费用原子（n 同色 / n 无色 / n 特定色）；3 种结构（纯同色 / 纯无色 / 特定色+无色）；切换费用 1 无色且无每轮限制；调律 = 1 张牌 + 0 骰子；全万能可满足同色要求；对手骰子颜色隐藏，数量公开。**支付时的骰子选择是一个战略动作**，编码为联合复合动作（而非子动作）。

**MVP 约束**：代码必须为 `MAX_ACTIONS` 增长（64 → 128 → 256）、动作的骰子组合特征向量以及 16 个新计数器槽留有空间——所有这些均无需架构变更。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D8：基于特征的卡牌与角色嵌入，可配置观察维度

**问题**：未来将有 1000+ 张卡牌和 100-300 个角色。
按 ID 查找表不能高效扩展。

**决策**：卡牌和角色的表示从 **DSL 元数据提取的特征**计算得出，而非按 ID 查找表。特征 MLP 在所有卡牌/角色间共享，提供零样本泛化：具有相似特征的新实体无需重新训练即可获得相似嵌入。

观察维度（`ObsMaxCardTypes`、`N_HOOKS` 等）在**运行时从引擎查询**，而非硬编码。网络嵌入表按物理上限定大小（`MAX_CARDS=2048`、`MAX_HOOKS=8192`、`MAX_CHARS=512`），以适应增长而无需架构变更。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D9：用于确定化的 CardPoolSpec 接口

**问题**："对手的牌库从哪里来？"这个问题会随时间变化——今天是共享池，中期是从大池独立采样，长期是贝叶斯推断。

**决策**：引入 `CardPoolSpec` Python 协议。IS-MCTS 代码只依赖协议接口；升级模型只需替换实现。

具体实现（按未来交付顺序）：
- `SharedFixedPool` — MVP
- `UniformFromPool` — 中期
- `BayesianFromPlayHistory` — 长期

**`max_copies`** 是一个新概念：每张卡有可配置的副本上限（默认 2），在 DSL 中逐卡声明。`SharedFixedPool` 使用此限制来约束初始构牌和确定化采样器的合法性检查。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D10：领域随机化——自对弈每局随机抽样队伍与卡牌

**问题**：网络需要学习元层面的规律，例如"角色 X 和 Y 有协同效应"。这需要在许多队伍组合上训练。

**决策**：自对弈**每局**从对局配置的范围中随机化游戏设置——队伍大小、角色、卡池。配置描述的是设置的**分布**，而非单一固定场景。网络不能专精于某一支队伍。

**次要效果**：这事后解释了为何 PPO 的阶段过渡持续崩溃——每个阶段专精于其阶段特定设置，而边界处的分布偏移是单智能体 PPO 无法吸收的。领域随机化是标准的 AZ 解决方案。

**实现状态**（2026-04-18 更新）：**已实现并通过 C1v7 验证**。
`ScenarioConfig` 支持 `char_pool` + `team_size` 随机采样（`random_1v1_config`），
每局 `sample_teams(rng)` 重抽。`disjoint_teams=True` 对 team_size≥2 防 cross-team
overlap 触发 #152 hook 双注册。详见 `training/az/config.py::ScenarioConfig`。
C1v7 (5-char pool, team_size=1) argmax vs mcts_200 = 0.45，首次公平泛化验证。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D11：构牌作为未来阶段，通过新引擎阶段 + 策略头引入

**决策（延后）**：构牌最终将被建模为与现有阶段并列的新引擎阶段 `PhaseDeckbuild`。
网络增加第二个策略头 `deckbuild_policy_head`；价值头和主干共享（D3）。自对弈每局运行两次 MCTS（一次用于构牌，一次用于战术），共享同一网络。

**MVP 不实现其中任何内容**，但 MVP **必须保持网络架构对此开放**（添加第二个头应只需几行修改）。

---

### D12：MCTS 决策粒度 = 复合游戏动作，不做抽象

**问题**：能否通过让智能体在高层面选择"做什么"并将"如何支付"推迟给求解器来降低 MCTS 成本？

**决策**：**不行**。GICG 机制是路径依赖的：调律的效果取决于调律时的出战角色；增益的目标在打出时快照。相同的抽象动作序列因顺序不同会产生不同结果，因此求解器无法在不重跑 MCTS 的情况下事后重建预期计划。

**含义**：
- 每个决策点的合法动作枚举是完整的笛卡尔积（类型 × 骰子组合 × 目标 × 调律来源）
- `MAX_ACTIONS` 初始为 128，在高度灵活情况下最多 256
- **不做转置**——到达同一"最终资源状态"的不同路径保持为独立的树节点，因为它们的中间状态是价值头的训练信号

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

### D14：ExpandUnionK 废弃(2026-04-21 commit `29ca0c4`)

**问题:** r003(2026-04-20)引入 `ExpandUnionK=3`,意在让 MCTS expansion
考虑 top-K 个 network action 的 union(而非单 argmax)加上 dice
变体,缓解确定化下只见单点 sample 的偏差。r005A 事后消融实测 K=3
**净负 0.05**(vs_mcts_200 0.45 → 0.40),且 r003/r004 训练过程
policy loss 改善但 argmax 胜率反而下降(反向相关,登记在 registry 中)。

**根因定位(事后诊断):** ExpandUnionK 只在 **dice 维** 枚举 union
分支,不在 **hand/deck** 维扩展。D1 新动作覆盖率埋点显示当前
实现只涵盖 <20% 的 D1 触发场景 — 即大部分新动作源自 card draw +
play 的隐藏状态,不是 dice。结果:K=3 **增加** MCTS 计算成本,
增加 π_target 形状扭曲,但不解决它本应解决的 D1 问题。

**决策:** 全量移除 `expand_union_k` 配置、MCTS union expansion 代码
路径、相关 observation 位。r001 风格单 argmax expansion 恢复为默认。

**代价:** D1 问题未解决,由后续 A1 方案(D1 actions network-informed
prior)接手;A1 单独 scope,不复用 ExpandUnionK 代码。

### D13：通过搜索深度 argmax 比较发现连携（延后，可选）

**问题**：罕见连携（每局不到 1 次）需要专用训练信号；随机初始化的 AZ 可能错过它们。

**已拒绝的替代方案**：绝对 Q 跳跃阈值（任意超参数）；Q 与兄弟节点比较（在早期训练中脆弱）。

**决策**：在单次 MCTS 搜索期间，在 rollout 检查点 `[50, 100, 200, 400]` 记录 `argmax_visits(root)`。若最终最佳动作与早期检查点的最佳动作不同，且在最后两个检查点间保持一致，则触发"发现事件"。信号是相对的且为二值——无绝对阈值。

**两种使用模式**：
- **模式 A（MVP 默认开启）**：作为轨迹元数据记录；回放缓冲区优先采样包含发现的游戏
- **模式 B（响应式升级）**：检测到后，将当前搜索扩展 30% 更多 rollout 以精炼新的最佳动作

**与 D6 的关系**：模式 B 是 D6 bootstrap 停滞升级方案的第 2 步。

**详情**：[归档设计](../../openspec/changes/archive/0005-az-decisions-d1-d14/design.md)

---

## 保留、重构与废弃的内容

### 完整保留（算法无关的基础）

- `gicg_engine/` — Go 引擎、解释器、capi
- `data/` — DSL 内容
- `gicg_engine/record/` — 事件日志、回放、export_view、replay_to
- `web/` — 回放 + 实时对战 UI
- `gicg_env/engine.py` — ctypes 绑定、snapshot/restore/clone
- `Game.snapshot() / restore() / clone()` — 已存在且经过测试

### 重构（调整但不重写）

- `gicg_env/env.py::GicgEnv` — 去除奖励塑形，简化
  `step()` 签名为 `(obs, done, info)`，移除新卡追踪
- `training/az/network/actor_critic.py::ActorCritic` 主干 — 保留编码器和
  交叉注意力，将策略采样替换为访问计数 CE 损失，
  将价值 GAE 替换为结果 MSE，移除 per-env 缓存
- `CardEncoder` / `CharEncoder` — 扩展以在现有槽计数输入的基础上消费特征向量
- 观察布局 — **已在** `observation.go:309-393` 处正确处理视角；无需变更

### 废弃（PPO 专用）

- `training/ppo.py`、`training/rollout.py`、`training/selfplay.py`、
  `training/stage_loop.py`、`training/opponent_pool.py`、
  `training/reward_norm.py`
- `training/tests/test_opponent_pool.py` 及其他 PPO 专用测试
- `configs/curriculum/`、`configs/stages/phase*.toml`
- 绑定到 PPO rollout 生命周期的注意力诊断钩子（如有）

---

## 计划概览

完整任务待办（含依赖和时长估算）见 [归档任务](../../openspec/changes/archive/0005-az-decisions-d1-d14/tasks.md)。

| 阶段 | 目的 | 时长 |
|---|---|---|
| B | 核心训练栈（B0-B7） | 约 7.5 天 |
| C | 在 MVP 场景上验证（C1-C4） | 约 3-5 天 |
| D | PPO 栈清理（D1-D4） | 约 2-3 天（延后） |
| E | 扩展功能（骰子、角色、构牌） | 未来 |

**到功能性 AZ 的总时长：12.5–15.5 天，外加清理工作。**

---

## 待解问题 / 延后议题

这些问题在讨论中提及但未锁定在 MVP 范围内。大多数将在 C 阶段或之后决定。

- **卡牌/角色的特征提取**：DSL 中的具体特征、MLP 还是注意力块。MVP 使用朴素特征 + 2 层 MLP，根据消融实验迭代。
- DSL 中的 **`max_copies`** 字段语法。用户倾向于逐卡设置，配合全局默认值。
- **竞技场评估频率和替换阈值**：默认值为 `每 500 局，>55%`，在 C 阶段调优。
- **并行自对弈 worker 数量**：取决于硬件。
- **Dirichlet 噪声参数**：默认值 `alpha=0.3, eps=0.25`。
- **大卡池的确定化采样器**（`UniformFromPool`）：非 MVP。

---

## 决策矩阵摘要

| ID | 决策 | 状态 |
|---|---|---|
| D1 | MCTS 在 Python 中实现 | 已确认 |
| D2 | IS-MCTS 单棵树配合 N_avail | 已确认 |
| D3 | 单一网络，共享主干 + 价值头，多头策略 | 已确认 |
| D4 | 无对手池 | 已确认 |
| D5 | 仅终局 ±1 奖励 | 已确认 |
| D6 | 随机初始化的 AZ，配合 bootstrap 监控 + 升级方案 | 已确认 |
| D7 | 骰子机制（原计划延后，现已端到端实现） | 已实现 |
| D8 | 基于特征的嵌入，可配置维度 | 已确认 |
| D9 | CardPoolSpec 接口 | 已确认 |
| D10 | 每局自对弈进行领域随机化 | 已确认 |
| D11 | 构牌阶段通过新头 + 引擎阶段实现，延后 | 已确认 |
| D12 | MCTS 粒度 = 复合游戏动作，不做抽象，不做转置 | 已确认 |
| D13 | 通过搜索深度 argmax 比较发现连携，延后 | 已确认 |
| D14 | ExpandUnionK 废弃(只覆盖 dice 维,D1 <20%,净负 0.05) | 已确认(2026-04-21) |

---

## 修订历史

- 2026-04-14（初稿）：D1-D11 记录自一次对话，起因于 phase1b 平台期事件和 MCTS 对比策略可行性探测。
- 2026-04-14（修订）：D6 扩展了 bootstrap 监控 + 4 步升级方案。D7 扩展了骰子选择的联合复合动作。在两个路径依赖实例后新增 D12（无动作级别抽象）。新增 D13（通过检查点比较发现连携）。
- 2026-04-14（骰子规格）：D7 扩展了完整的骰子机制规格。计数器数量从 12 更新为 16。
- 2026-04-14（文档重组）：从 `docs/decisions/` 拆分至 `docs/current/az/`，并附带专题子文档。实现细节移至 `mcts_design.md`、`network_design.md`、`dice_spec.md`、`training_loop.md`、`determinization.md`。证据移至 `evidence/`。本文件现为顶层决策日志。
- 2026-04-18（D10 状态更新）：C1v7 落地并完成首次公平泛化验证（argmax vs mcts_200=0.45）。D10（领域随机化）从"未实现"更新为"已实现"。结构性 sid pinning + struct_readout 架构改动未引入新 ADR（属于 D8 的实施细节）。
- 2026-04-23（新增 D14）：ExpandUnionK 废弃决策补记。事发 2026-04-21 commit `29ca0c4` 已删代码;2026-04-23 补记决策条目。根因:只覆盖 dice 维不覆盖 hand/deck,D1 <20% 触发场景,净负 0.05。配套 r001-r006 ablation 总结见 `../5_history/ablations/r001_r006_ablation.md`。
- 2026-04-26（docs 大改）：从 `docs/current/az/decisions.md` mv 到本路径 `docs/2_decisions/adr-0005-az_decisions_d1_d14.md`。原"docs 路径重组"段落 (2026-04-14) 描述的内部子文件名 (mcts_design / network_design / dice_spec / training_loop / determinization) 现位于 `../1_specs/` 下,具体路径见 `../README.md` 索引。
