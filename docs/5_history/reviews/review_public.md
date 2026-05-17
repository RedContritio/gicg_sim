# GICG AI 训练技术路线说明（公开版）

> 2026-04-17。本文是一份独立的技术路线说明，不依赖阅读代码库或训练记录。
> 面向对强化学习、MCTS、游戏 AI 有背景知识的评审人。内部带代码/artifact
> 引用的版本见 `review_internal.md`。
>
> **更新 2026-04-17 晚**：扰动诊断把先前推断的"shortcut learning"修正
> 为一个训练基础设施 bug——神经网络主干里的 HookEncoder 意外脱离了
> 反向传播图，参数在 weight decay 下指数衰减到零。详见第 10 节（新增）。
> 所有先前训练结论都是在这个 bug 存在的前提下得出的；核心架构假设的
> 公平测试推迟到修复后的 C1v6 run 完成。

## 0. 最新结论

F run 后跑扰动诊断发现训练出来的网络对 hook 通道完全无响应。最初归因
为 shortcut learning，进一步查参数值发现 HookEncoder 的 Transformer
参数整体衰减到 1e-30 到 1e-40 量级。

根本原因：hook embedding 在静态观测缓存阶段被 `torch.no_grad` 计算并
通过 numpy 序列化存入回放缓冲。训练前向从缓冲读回时已经脱离计算图，
HookEncoder 的梯度永远为 None，而 weight decay 每步仍然乘以
`(1 - lr · l2_coef)`，几千步后指数衰减到零。

含义：
- 所有先前训练跑（C1v1–F，共约 5000 局）都是在 HookEncoder 权重近零
  的前提下进行的
- 这个项目的核心架构假设——"从 hook token 序列学习游戏规则而非从槽
  位 ID 学习指纹"——**从未被公平测试过**
- 先前对失败的归因（"d_model 太小"、"领域随机化不够"等）都需要在
  修复后的 run 上重新评估

修复方案：把原始 hook token 序列而非预编码 embedding 存进回放缓冲，
训练前向时重跑 HookEncoder 让梯度流动。顺便审查出并修复了另外 5 个
网络相关的次要问题。

C1v6（修复后首个训练）进行中。先前所有 checkpoint 作废。

---

## 1. 问题与目标

本项目目标是训练一个能玩"原神卡牌游戏（Genshin Impact TCG）"同人实现的 AI。
从机器学习角度看，它是一个**两人不完美信息零和回合制博弈**，具有以下特征：

- **隐藏信息**：对手手牌内容、对手牌库顺序、双方未来骰子点数、未来抽牌。
- **对局长度**：一局 10-15 回合，智能体在每局做 30-40 次决策。
- **动作空间**：每个决策点合法动作通常 10-60 个，最坏情况可达几百（受骰子支付组合枚举影响）。
- **游戏内容持续增长**：角色和卡牌数量未来会从几个扩到百/千级，每次扩充会引入新机制（新元素反应、新 buff 交互方式）。

上述最后一点决定了**泛化是硬要求**，不是 nice-to-have。一个只能在训练时看到的角色 / 卡池上工作的 agent 在真实使用中是无效的。

## 2. 为什么不用 PPO / 标准 actor-critic

项目早期（2025-Q4 到 2026 年初）用 PPO 自对弈 + 课程学习跑。这条路线在 phase1b 阶段（2v2 L1+L2 场景）陷入持续回退，而不是 plateau——Δ 胜率在连续训练下越训越差。

关键的可证伪实验：我们把一个训练了 1500+ iteration 的 PPO checkpoint 和一个**没有任何学习组件**的纯 UCT + 随机模拟 MCTS 玩家（200 rollouts/决策）在三个场景各跑 40 局。结果是 120 局里 MCTS 117 胜 3 负，综合胜率 97.5%。其中在 phase1b 失败的那个 2v2 场景，MCTS 40 战全胜。

这个结果的启示：

1. **搜索在这个问题上严格强于单纯的神经网络策略**——纯搜索不需要任何训练，就能彻底碾压 1500 iteration 的 PPO。
2. **PPO 的持续回退不是超参问题**，是单智能体 RL 在两人不完美信息零和博弈下维持自对弈均衡的结构性困难。每个课程阶段 agent 在自己的子场景里过拟合，阶段过渡时分布偏移打散了之前学到的策略。
3. **方向不对，再调 PPO 的 reward shaping / hyperparam / architecture 都是徒劳**。

这直接决定了转向 AlphaZero 风格的 MCTS + 神经网络协同训练。

## 3. 算法框架的核心选择

### 3.1 信息集 MCTS（IS-UCT），不是 PIMC

两人不完美信息博弈的 MCTS 有两种常见做法：

- **PIMC**（Perfect Information Monte Carlo）：在 MCTS rollout 时允许搜索方"透视"对手隐藏信息（假装知道对手手牌），这有已知的"偏差"——agent 学到的是完全信息下的最优策略，在真实部分可观测下性能退化。
- **信息集 MCTS**（Cowling, Powley, Whitehouse 2012：IS-UCT）：每次 rollout 独立采样一组合理的对手隐藏状态（"确定化"），用同一棵搜索树跨多次确定化累积统计。用 `N_avail`（动作在多少次 rollout 里合法）修正 PUCT 探索奖励，避免罕见合法动作因访问数少被错误 underexplore。

我们选 IS-UCT。PIMC 的透视偏差会污染训练数据——训练时让网络以完整信息看世界，部署时却只能看部分信息，直接造成 train/test 分布失配。IS-UCT 没有这个问题。

另一个实际简化点：两人博弈中智能体自身的动作合法性在不同确定化之间是稳定的（自己的手牌自己知道），只有对手节点需要合法性过滤。这让 IS-UCT 实现难度比通用的 IS-MCTS 低很多。

### 3.2 叶节点评估用 rollout + network 混合，不是纯网络

标准 AlphaZero 的 leaf evaluation 直接用网络的 value head 输出，不做 random rollout。我们发现这**在小网络和早期训练下是破坏性的**：

一个消融实验：在 IS-MCTS（100 rollouts）下比较叶评估方式。用**随机初始化**的网络 value head 做叶评估，对 random 玩家胜率 20%。同一个 IS-MCTS 引擎，换成 random playout（rollout 到终局）作为 value 估计，对 random 玩家胜率 90%。

含义：小网络（我们用 d_model=128 量级）在训练早期的 value head 输出是纯噪声加偏差，用来做 PUCT backup 反而让搜索**比均匀探索还差**。AlphaZero 原始能跑通是因为网络参数量到亿级能在几百万步自对弈后把 value head 训得稳定，我们的算力（单机 M 系列 CPU）做不到这种规模。

解决方案参考 AlphaGo 原论文（Silver et al. 2016）：叶评估是 `V(leaf) = λ·V_net(leaf) + (1-λ)·V_rollout(leaf)` 的混合。我们在此基础上加了**训练中线性退火 λ**：训练开始 λ=0 纯 rollout 兜底搜索质量，随着网络变强 λ 线性升到 0.8（当前设置），让网络逐步接管。

这个策略在 4 个消融 run 中验证：
- λ=1 纯网络：训练 2000 局，gauntlet vs mcts_200 始终 ≤ 5%（网络越训越差）
- λ=0 纯 rollout：1000 局达到 45-50%，但因为网络不参与搜索，无法"变强"
- λ=0.3 固定：500 局没有显著改善，网络噪声通过 30% 权重轻微毒化搜索
- λ 退火 0→0.8：1000 局达 45%，单调上升趋势（10% → 25% → 45%）

λ 退火是**必要的非标准调整**，不是"为了偏离 AZ 而偏离"。

### 3.3 Virtual Loss 并行 rollout + 跨 worker 推理服务

训练吞吐瓶颈拆解：在单 worker 同步 MCTS 下，大量时间浪费在等待单次网络 eval 返回上。工程优化两条路：

1. **Virtual loss**（Segal 2010）：单 worker 内并发发起多条 rollout，虚扣 N/W 避免重复走相同路径。单 worker 实测 1.94× 加速。
2. **跨 worker 推理服务**：所有 worker 的 leaf eval 请求统一走 pipe 发到一个独立的 inference server 进程，server 动态 batch（最多 32 个请求或 3ms 超时）后一次 forward 返回。这把碎片化的 batch=1 matmul 合并成 batch=4-16。

推理服务同时承担**异步训练**：主进程独立训练，周期性推送最新 weights 给 server；worker 接收的是略微滞后的 weights（stale 10-30 局）。Lc0 / ELF OpenGo 的工程经验显示这种异步下网络仍然收敛——AZ 的训练目标 z（终局胜负）和 π_mcts（MCTS visits）在技术上对 worker 当时的 weights 是 on-policy 的，没有系统偏差。

## 4. 表征设计：反 ID、hook tokenization、shuffle

### 4.1 问题：如何让网络学到"规则"而非"指纹"

传统做法是给每张卡 / 每个技能分配一个 ID，网络通过 embedding table 学到每个 ID 的语义。这种做法**严重阻碍泛化**——训练时 agent 看到的是"ID=17 → 造 2 伤害"的映射，新卡（ID=18）在 embedding table 里是随机初始化，完全没见过。

我们选择的方案：**agent 永不看到 ID，只看"功能特征"**。具体：

- 每张卡、每个技能的效果（打 N 点火伤、加 M 点护盾等）在 DSL（我们自定义的 Lua 子集）里以事件回调（"hook"）的形式描述。这些 hook body 在加载时被 tokenize 成 `(token_type, token_value)` 序列。
- 观测（observation）里包含所有激活的 hook 的 token 序列。网络有一个 Transformer（HookEncoder）消费这些 token 序列，输出 per-hook embedding。
- 每局游戏开始时，所有 counter 槽位 / hook 槽位 / 卡牌 ID 都被**随机 shuffle**，agent 永远看不到稳定的"位置 X = 赤蝶的枪技"。

理论上，网络应该学到"token 序列 `deal_damage + TokLitNumber(2) + Element.Fire` 表示打 2 点火伤"的**结构化语义**，而不是"某个槽位里这个 ID 对应这个效果"。新卡上线时，它的 token 序列走的是同一个 HookEncoder，网络应该能直接处理。

### 4.2 数值 token 的序关系

token 类型（如 `TokLitNumber`=240）走 embedding table。token value（具体数字 2、3 等）走一个独立的 `Linear(1, d_model)` 标量投影。两者加上 positional embedding 后作为 token 的输入 embedding。

这个设计让数值 token 之间有**天然的序关系先验**：`Linear(1, d)` 对标量线性，`value_proj(2)` 和 `value_proj(3)` 在 embedding 空间严格相邻，`value_proj(4)` 也严格相邻。网络不需要从数据里学"2 < 3 < 4"的数字序关系，它由网络架构本身保证。

### 4.3 关于"反 ID + 功能特征"的已知未验证假设

这条设计的核心假设是"网络能从 hook token 序列学到结构化语义"。**这个假设当前只部分得到验证。**

在一轮单角色对称训练的产出模型上，我们做了扰动诊断：

- **counter value 扰动**：把观测里某个 counter 的值加减 ±5，网络输出 value 大幅变化（-0.99 → +0.97），top1 prior 动作变化。
- **hook token 扰动**：把某个 hook 的 token（包括数值 token 和类型 token）改成任意其他合法值，网络输出**完全不变**。

含义：这个训出的网络**学到了完全忽略 hook channel，只看 counter values**的捷径。

**根因解释（待验证）**：训练场景是单角色（赤蝶）对称对战，每局所有 hook 都一样，hook channel 的信息熵为零。网络发现 counter values 足够预测胜负，hook channel 被 pruning 掉了。

**验证方案**：把训练场景切换到多角色随机采样（5 个角色，每局独立采样阵容），此时 hook channel 因场景变化有信息熵。重训后用相同扰动脚本测，如果网络对 hook 扰动开始响应，则假设成立；如果仍麻木，需要重新审视 HookEncoder 架构或加更强随机化（卡池混合、数值扰动）。

**这个验证 run 正在进行中**。中期指标（arena 胜率、loss 趋势）全部健康，但最终扰动测试结果还未知。这是项目当前最重要的单个未解问题。

## 5. 领域随机化（D10 决策）

标准 AlphaZero 在围棋 / 国际象棋等问题上不需要"领域随机化"，因为规则固定不变。我们的问题不同——未来会持续加入新角色、新卡牌，需要 agent 能泛化到未见过的组合。

实现：每局自对弈独立从角色池采样一对阵容。训练分布是**组合分布**而不是固定场景。

arena（新网络 vs 旧网络的胜率测试）和 gauntlet（新网络 vs 固定强度基线如 mcts_50/mcts_200 的绝对强度测试）**仍用固定阵容**，作为跨训练 run 可比较的参考点。如果 eval 分布也随机化，每次 run 的数字会因采样方差漂移，跨 run 对比就不成立。

领域随机化这条决策在项目启动时就在设计文档里，但**实际代码长期未实现**——`scenario` 配置里阵容字段是固定的，多轮 C 阶段消融都跑在单角色对称场景。这是上文 Section 4.3 反 ID 假设未能验证的直接原因。当前 F run 补上这个实现。

## 6. 架构工程决策

### 6.1 三层分离：DSL / Go 引擎 / Python 训练

**DSL 层（Lua 子集）**：描述所有具体游戏规则。用 Lua 子集而非 JSON 是因为游戏规则需要条件分支、局部变量、闭包（捕获 slot-aware 的角色引用）。JSON 无法表达这些。Python 作为 DSL 会带 GIL + 沙箱安全复杂度。Lua 子集只支持 6 个语法结构（local/if/return/arith/table/function），禁用循环和 pairs/ipairs，AST 解释器约 1200 行 Go 代码可审计。

**Go 引擎层**：纯通用执行器，完全不知道 HP、能量、元素、护盾、冻结等**任何游戏概念**。它只知道：counter（带 clamp 和 min/max 的数值槽位）、hook（按 HookType 分发的回调）、事件栈、snapshot/restore。所有游戏规则（死亡判定、元素反应、能量回复）都是 DSL counter + hook 写的。

引擎不懂游戏规则有两个直接好处：
1. **新增机制不需要改引擎**——完全在 DSL 层加。
2. **引擎代码小而稳**（几千行 Go），Go 端测试能覆盖 corner case（mirror match 绑定、死亡强制切换、回合翻转等），不需要每次 DSL 改动都测引擎。

**Python 训练层**：只管 MCTS 树和深度学习。通过 ctypes 调 Go 引擎的 c-shared library。

### 6.2 为什么 MCTS 不做 Go，继续 Python

常被挑战的一个决策。Go 更快是对的，但性能实测显示**瓶颈不在 tree descent**：

训练场景下 time profile 大致：
- 网络 eval RPC（包括 pipe 往返和 torch forward）：约 74%
- random rollout（在 env 里做随机步进）：约 16%
- env step / env query（tree descent 时的引擎调用）：约 5%
- 确定化采样 / snapshot restore：约 5%

把整个 MCTS tree 搬到 Go 只能省那约 5%。最高 ROI 的 Go 优化是把 random rollout 搬过去（理论可以把 rollout 部分加速约 10-50×），但整体训练加速估计只有 1.15-1.30×。工程代价 1 天 + 对齐测试，对比这个收益 ROI 不突出。

真正的性能优化点是降低 network forward 开销，或在 MPS GPU 拐点翻转后用 GPU。这两个都独立于 MCTS 语言。

### 6.3 网络容量 d_model=128 的选择

单机 M 系列 CPU 是硬约束。d_model=128 下 batch=4 单次 forward 22-28 毫秒（实测）。batch scaling 接近线性（batch=16 耗时约 16× batch=1），batch 不摊薄——这是 CPU 矩阵乘对小矩阵的特性。

d_model=256 估计单次 forward 4× 变慢，训练吞吐从 50 games/hour 掉到 10 games/hour 以下，每个 C 阶段消融从 12 小时变 48 小时，迭代速度不可接受。

MPS GPU 在 d_model=64 时比 CPU 慢 3-4×（kernel launch overhead 主导小 matmul）。d_model=128 拐点还没测，这是接下来首个待跑的 bench。如果 MPS 有效可能能升到 256。

## 7. 当前验证状态

**已验证**：
- 纯搜索（无网络）在这个问题上严格强于 1500 iteration 的 PPO（117-3 对战结果）
- IS-MCTS + AlphaGo-mode leaf 混合 + λ 退火的训练管线能收敛（loss 单调下降、arena 持续换章、gauntlet 对固定基线胜率随训练单调上升）
- 网络单靠 counter values 能学出一个"在训练场景内显著强于随机"的策略
- 推理服务架构支持 stale weights 异步训练，收敛不被污染

**已发现的问题**：
- 在单角色对称训练下，网络完全忽略 hook channel——"反 ID + 功能特征"的设计没能在这种退化场景下激活。

**正在验证（最关键未解问题）**：
- 领域随机化（5 角色每局采样）能否激活 hook channel？即：agent 能否学到"从 hook token 序列读游戏规则"而不是"看 counter values 猜"。结果二元——如果激活，项目架构基础稳固；如果仍麻木，需要更强随机化或重新审视 HookEncoder。

**待后续验证**：
- λ 退火在多角色场景下是否能同样收敛
- MPS GPU 在 d_model=128 上是否可用
- team_size ≥ 2 场景是否暴露新的引擎边界 bug

## 8. 可能被挑战的选型 · 预先理由

### Q1：为什么 MCTS 用 Python 不用 Go？
因为性能 profile 显示 tree descent 只占 5%，瓶颈在 network eval。把 MCTS 搬 Go 工程代价 > 整体训练加速收益。详见 Section 6.2。

### Q2：为什么 IS-UCT 而不是 PIMC？
PIMC 有透视偏差导致 train/test 分布失配。IS-UCT 单树 + N_avail 是标准答案（Cowling 2012）。详见 Section 3.1。

### Q3：为什么 λ 退火，不是纯网络 leaf eval？
消融实验证实：d_model=128 量级在早期训练下，网络 value head 是噪声 + 偏差，纯网络 leaf eval 让搜索劣于均匀探索。AlphaGo 原论文本身就是 rollout+network 混合，这是对小模型受限算力的必要调整。详见 Section 3.2。

### Q4：d_model=128 是不是太小？
单机 CPU 是硬约束。d_model=128 单次 forward 已经 22-28 毫秒。更大网络吞吐崩塌到实验迭代不可行。未来 MPS 拐点翻转后可升。详见 Section 6.3。

### Q5：为什么前期消融都在单角色场景，"验证管线"和"验证泛化"被分开？
这是分步实验方法论。C 阶段前 4 个消融（C1v1-v4）的目标是定位 λ 退火策略、arena/gauntlet 机制、inference server 稳定性——这些是实验设施问题。确认设施 work 之后才把场景推到多角色去测泛化。G3 扰动诊断显示 C1v4 网络没学到泛化，这是被**预料到**的单角色退化场景 artifact，不是 surprise。

### Q6：Hook tokenization 真能让网络学到规则？
**不是已验证的事实，是项目当前最大的未解假设**。Section 4.3 详述。F run 正是这个假设的可证伪实验。项目对这个假设没有盲目自信，有清晰的失败判据和 fallback（更强随机化、或重审 HookEncoder）。

### Q7：stale weights 异步训练污染 off-policy？
Lc0 / ELF OpenGo 工程经验：stale 100+ 局仍收敛。AZ 训练目标 z（终局实际胜负）和 π_mcts（worker 当时 weights 下的 visits）在技术上都 on-policy。我们 stale 上限 10-30 局，在安全区内。详见 Section 3.3。

### Q8：每局构造新 env 的 DSL 加载开销？
实测 env 构造约 200ms，单局总耗时 5 分钟，构造占比 <1%。不是瓶颈。真瓶颈在 eval RPC。

### Q9：MuZero 更好？
MuZero 主要解决 env 不可访问的场景（Atari、机器人）。我们的 env 是 Go 引擎完全可访问的确定性状态机，snapshot/restore 8μs O(1)。直接用真实 env 做 rollout 比学 world model 更稳更快。

### Q10：DSL 用 Lua 子集是不是过度工程？
游戏规则需要条件分支 + 局部变量 + 闭包，JSON 表达不了，Python 带 GIL + 沙箱复杂度。Lua 子集解释器约 1200 行，可审计。详见 Section 6.1。

### Q11：arena/gauntlet 和 train 分布不一致怎么办？
**主动选择**。需要跨 run 可比的绝对强度参考点，如果 eval 也随机化跨 run 数字不可比。代价是 eval ≠ train 分布，未来可加 round-robin 覆盖多 matchup。详见 Section 5。

### Q12：已知 bug 会不会影响验证？
已知的 mirror match hook 重复注册 bug 当前通过 `allow_mirror=False` + arena/gauntlet 用非 mirror 固定阵容完全绕开。训练主线不受影响。bug 修复方向已定（hook 绑 counter 按值分发的"动态 hook 架构"），但不在 C 阶段关键路径，F 完成后再评估。

## 9. 项目状态总结

**已完成**：
- 从 PPO 迁移到 AZ 的基础训练栈（含 IS-MCTS、推理服务、异步训练、arena/gauntlet、λ 退火）
- Go 引擎 + Lua 子集解释器（引擎不懂任何具体游戏规则）
- Web UI（replay 回放 + human-vs-agent 对局，用作算法诊断工具）
- 骰子机制（8 种骰子、三种费用原子、确定化采样器扩展）
- 4 轮 C 阶段消融验证（管线能 work）

**进行中**：
- C1v6 训练，修复后首次真正让 HookEncoder 参与梯度更新

**待定**：
- C1v6 结果决定架构假设是否站得住（公平测试）
- 性能优化路径（MPS GPU bench、HookEncoder 轻量化）的 ROI 评估
- 构牌阶段（deckbuild phase）实现，作为第二个 MCTS 搜索阶段 + 策略头

---

## 10. Post-F HookEncoder 梯度断流诊断（2026-04-17 晚）

### 10.1 从 shortcut learning 到 infrastructure bug

F run 完成后按第 7 节的计划跑扰动诊断：在固定一个中期游戏状态上，
扫描某个 hook 的数值 token，观察网络 value / policy 输出是否随之
变化。结果：对 hook 通道的任何扰动（数值 token、类型 token）都让
输出完全不变；对 counter values 的扰动则有正常响应。

最初诊断为 shortcut learning——即在单一场景训练下，counter values
本身足以预测胜负，网络因此跳过 hook 通道学到捷径。但扩散到 5 角色
随机阵容（F run）后仍然完全不响应，与 shortcut learning 假设不符
（阵容变化应让 counter 预测能力下降，逼网络用 hook 通道）。

深入诊断（5 级架构探针）发现：HookEncoder 的 Transformer 权重矩阵
几乎全部衰减到 `10^{-8}` 到 `10^{-40}` 量级。特别是 LayerNorm 的
gamma 参数初始化为 1.0，训练后测得 `3.87 × 10^{-39}`。这不是训练
收敛状态，是参数被持续乘一个小于 1 的因子几千次的指数衰减结果。

### 10.2 根因

HookEncoder 的 embedding 计算路径在训练和推理上是共享的：

- **推理**（MCTS 叶节点评估）需要高吞吐。每局开局一次算好 hook
  embedding 缓存，后续每次叶节点评估直接复用，不需要重跑 HookEncoder。
  这是性能优化，用 `torch.no_grad` 实现并把结果序列化到 numpy。
- **训练**从回放缓冲取 trajectory。缓冲里存的就是那个被 no_grad 和
  numpy 固化的 embedding。训练前向把它作为 tensor 参数传给网络，参
  与后续的 cross-attention 和头部计算。

缺陷：训练前向用的 hook embedding 已经脱离计算图。反向传播不会触
及 HookEncoder 的任何参数。但 AdamW 的 weight decay 仍然每步对所
有参数乘以 `(1 - lr · l2_coef)`。数千步训练后，HookEncoder 参数被
指数压向零。Transformer 各层退化为零输出，下游的 cross-attention
看到的 hook 方向是恒零向量，无论 token 输入如何扰动。

### 10.3 修复

核心修复：将 HookEncoder 的运行从"缓存-复用"模式恢复为"训练时重跑
带梯度"模式。具体：

- 回放缓冲只存 hook 的原始 token 序列（整型矩阵），不再存预编码
  embedding
- 训练前向每次从 batch 取出 token，**重新运行 HookEncoder** 得到
  带 grad 的 embedding，再喂给后续的 cross-attention 和头部
- 推理路径保持不变，继续用缓存的预编码 embedding（训练以外没有
  梯度需求）

这条修复让 HookEncoder 重新在梯度图里。单次实验验证：构造 synthetic
batch 跑 5 次训练步后，HookEncoder 所有参数梯度非零，Linear 权重
Δ/init 约 8%，LayerNorm gamma 重新偏离初始化。这是正常训练动态。

### 10.4 顺带修复的 5 项其他问题

同批审查网络时发现并修复：

1. **L2 正则化粒度**：正则化惩罚所有参数，包括 LayerNorm 的 gamma
   和所有偏置。LayerNorm gamma 初始为 1，被 decay 会削弱归一化强度。
   标准做法是只惩罚 2D 及以上的权重矩阵。修复后偏置和 LayerNorm
   gamma 豁免 L2。

2. **CounterEncoder 稀疏过滤用错标志**：网络为加速把非零 counter 筛
   掉 padding，原实现用 `counter_value != 0` 作为 "这个槽位有效" 的
   判据。但 0 是很多 counter 的合法值（护盾破、buff 结束、AP 耗尽
   等），这类归零状态信息被过滤丢失。修复：改用静态 obs 的 min/max
   构造 `active_slot_mask`（min 或 max 非零表示这个槽位承载真实
   counter），不看当前 value。

3. **GPU sync 点**：稀疏化代码里有 `.item()` 调用每次前向触发一次
   device↔host sync，对 MPS/CUDA 是每步几毫秒开销（CPU 无影响）。
   改用 on-device 的 `amax` + 一次 `int()`。

4. **Policy head 的 state 向量缺 hook pool**：原实现为避免 pointer
   net 退化，刻意不把 hook_pool 放进 state 向量，只让 value head 有
   hook 全局上下文。代价是 policy 只能通过 action embedding 的 gather
   操作间接用 hook 内容。修复：state 向量加入 hook_pool 与 value
   对称（4·d），pointer-net 退化风险由 action embedding 上的
   LayerNorm 和残差结构缓解；若事后测试发现 policy 仍不用 hook，可
   升级为 state-query 对 hook 做 attention pool 的 state-aware 版本。

5. **CardEncoder 数量双重放大**：卡牌 bucket 编码原实现把 token 向
   量乘以 count（`(tok + count_emb) * counts`），同时 pool 的分母
   又是 "有多少种 nonzero 的卡" 而不是卡牌总数。count=3 的卡特征
   被放大三倍，同时 count_proj 也编了一次 count，造成数量信号双重
   放大。修复去掉乘法，保留 count_proj 的加性贡献。

6. **HookEncoder dropout 硬编码 0**：其他注意力模块通过 config 接收
   dropout，HookEncoder 独立硬编码 0，不跟随全网。修复为参数化接收。

### 10.5 含义

项目先前的"hook tokenization 假设未被验证"的表述是轻了。正确的表
述是：**假设从未被测试**，因为每次训练都在 HookEncoder 死状态下
进行。第 7 节里的所有"hook 麻木"观察都不能归因给算法设计，只能归
因给这个训练基础设施 bug。

修复后的 C1v6 是首次公平的测试。具体验证仍是扰动法：训练完成后用
同一套 probe 脚本测 C1v6 的 champion checkpoint，观察网络是否对
hook token 扰动有响应。

同时 C1v1 "d_model=64 容量不足" 这个归因需要重新评估——在 hook 通
道死的前提下，value head 学不到泛化信号是必然，不能反推出 d_model
不够。修复后若再出现容量不足的症状，才能得出这个结论。

先前五轮验证（C1v1-F）的价值降级为"训练管线本身可以跑通"，不再作
为架构假设的验证证据。

---

## 参考文献

- Cowling, Powley, Whitehouse. "Information Set Monte Carlo Tree Search." IEEE Trans. on CIAIG (2012).
- Silver et al. "Mastering the game of Go with deep neural networks and tree search." Nature (2016).
- Silver et al. "Mastering Chess and Shogi by Self-Play with a General Reinforcement Learning Algorithm." arXiv:1712.01815 (2017).
- Segal. "On the Scalability of Parallel UCT." Computers and Games (2010).
- Lc0 project documentation on asynchronous training with stale weights.
