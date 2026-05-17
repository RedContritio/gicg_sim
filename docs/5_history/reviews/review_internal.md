# GICG 项目技术路线评审材料（内部版）

> 2026-04-17。给第三方评审用，带代码引用和实证数字。公开版见
> `review_public.md`。
>
> **更新 2026-04-17 晚**：F run 的"hook channel 麻木"被诊断为
> **hook_encoder 梯度被意外切断的 bug**，而非 shortcut learning。已修
> 复 + 同批修复网络其他 5 项潜在问题。详见本文第 12 节（新增）。C1v6
> 是首个在完整修复后跑的 run，hook channel 是否激活的判定推迟到
> C1v6 完成后用 probe_numeric_sensitivity 测 final_champion。

## 0. 最新结论（2026-04-17 晚补）

**F run 的架构假设验证结果被一个 training-infrastructure bug 污染**。

核心发现链：
1. F run 完成（500 局，arena 前 4 次都换章，gauntlet g500 vs mcts_200=25%）
2. 按 Section 9 计划跑 `tools/probe_numeric_sensitivity.py` 对 final_champion 扰动
3. 扰动 hook token 时 value/policy 输出完全不变，扰动 counter_values 时正常响应
4. 最初诊断为"shortcut learning"——但 5 级架构诊断（`tools/diag_hook_path.py`）显示
   **hook_encoder 所有参数权重都衰减到 1e-8 到 1e-40 量级**（LayerNorm weight 初始 1.0，现在 3.87e-39）
5. 根因定位：`encode_static` 在 `torch.no_grad()` 下算 hook_emb，经 numpy 序列化后存 buffer。
   训练 forward 从 buffer 读 hook_emb 是已 detach 的 tensor，**hook_encoder 参数永远 grad=None**。
   AdamW 的 weight decay 每步乘 `(1 - lr·l2_coef)`，几千步后指数衰减到 ~0。

这个 bug 意味着：
- C1v1-F 的**所有** ckpt 都是在 hook_encoder 权重近零的状态下训出来的
- "反 ID + hook tokenization" 这条核心架构假设**从未被公平验证过**
- Section 4.3 里"F run 是验证假设的实验"应改为"F run 是发现 bug 的实验，真正的验证推迟"
- 之前诸如 "d_model=64 不够" (C1v1 归因) 等结论在 hook channel 死的前提下都不牢靠

修复方向选定：hook tokens 存进 buffer（而非预编码的 hook_emb），训练时重跑
HookEncoder with grad。同时顺手修了另外 5 项发现的问题（第 12 节）。

**当前状态**：C1v6 在跑（400 局，每 100 局 arena，修复全部落地后的首训练）。
完成后重跑 probe 验证。所有先前 ckpt 作废。

---

## 1. 问题域

GICG 是原神卡牌游戏（Genshin Impact TCG）风格的同人两人不完美信息零和卡牌博弈。隐藏信息包含对手手牌内容、对手牌库顺序、双方未来骰子、未来抽牌。对局长度通常 10-15 回合，30-40 步交互。

最终目标是训练一个能跨角色组合、跨卡池泛化的 AI，在新卡牌上线时以零样本或少样本适应。"泛化"是硬要求，不是 nice-to-have，因为游戏数据本身在持续增长（未来预期 100-300 个角色、1000+ 张卡牌）。

## 2. 总体架构（三层）

第一层 Lua DSL 数据层（`data/characters/`、`data/cards/`、`data/system/`）描述所有具体游戏规则：角色技能、卡牌效果、伤害管道、元素反应、回合流程。所有游戏机制都以 counter（数值状态）+ hook（事件回调）形式编码。文件按角色/卡牌/系统分层组织。

第二层 Go 引擎（`gicg_engine/`）是纯通用执行器，不包含任何游戏规则知识。引擎只知道：角色有几个、手牌和牌库是一组卡牌身份、回合和行动轮、事件栈。引擎不知道 HP、能量、元素、护盾、冻结、AP 这些概念——它们全是 DSL counter + hook 的产物。引擎提供：counter 存储（带 clamp 和写钩）、hook 分发（按 HookType + Priority 排序）、事件栈（支持嵌套 + 延后队列）、合法动作枚举（纯结构化，不做条件判断）、snapshot/restore/clone。此外 Go 引擎还有一个 Lua 子集的 AST 解释器（`interp/`），能解析和执行 DSL。

第三层 Python 训练层（`training/`）只管 deep learning 和 MCTS 树。通过 ctypes 调用 Go 引擎的 c-shared library（`libgicg.dylib`）。

依赖方向单向：DSL → Go 引擎 → Python 训练。上层不能写下层。

## 3. 观测与动作

观测分静态部分和动态部分。静态部分每局产生一次（约 221KB）：所有 counter 的元数据（min/max/shuffled_sid）+ 所有 hook 的 token 序列（900 hooks × 120 tokens × 2 fields）。动态部分每步产生（约 8KB）：3 个 meta（phase/round/is_my_turn）+ 1832 个 counter 当前值 + 手牌/牌库/弃牌堆的桶计数。

关键设计：所有 ID（card_ref、skill_id、counter 槽位）每局随机 shuffle 后才写入观测，agent 永远看不到稳定的 ID→语义映射。Agent 必须从 counter 值的变化、hook token 的内容结构学习，而不是记忆"槽位 X = 赤蝶枪"。

动作空间是每个决策点的合法动作笛卡尔积（kind × skill/card 引用 × 骰子支付组合 × 目标），上限 MAX_ACTIONS = 2048。策略头是指针网络：用主干 pooled 向量对每个合法动作的特征（hook embedding + dice_combo 投影 + 目标角色 embedding）做内积，然后 softmax。

## 4. 网络结构

共享主干 + 值头 + 多策略头。d_model = 128，2 层 cross-attention，dropout 0.1。主干组件：
- HookEncoder：Transformer（2 层 × 4 头），把 hook token 序列编码成 per-hook embedding。token type 走 embedding table（vocab=256），token value 走独立的 `Linear(1, d_model)` 标量投影，两者加上 positional embedding 相加作为每个 token 的输入。这个设计让数值 token 之间有天然的序关系先验——`Linear(1, d)` 对标量线性，`value_proj(2)` 和 `value_proj(3)` 在 embedding 空间严格相邻。
- CounterEncoder：counter 值经 `Linear(1, d)` 投影 + per-slot ID embedding 相加。只保留非零 counter（稀疏化）。
- CardEncoder：hand/deck/discard 桶计数 × per-slot embedding，非零项 pool。
- CrossAttention：counter embeddings 和 hook embeddings 双向注意力 2 层。
- 最终 pool 成 d_model 向量喂值头和策略头。

值头 tanh 限界到 [-1, 1]。策略头是指针网络，输出 MAX_ACTIONS 个 logits，非法位置 mask 成 -inf。

未来会加 deckbuild 策略头（构牌阶段），主干和值头共享。当前未实现，网络架构保留插槽。

## 5. MCTS 算法

采用 IS-UCT（Cowling, Powley, Whitehouse 2012）。单树信息集 MCTS，每次 rollout 在根节点确定化一次隐藏状态（采样对手手牌内容、对手牌库顺序），用 `N_avail` 簿记哪些动作在这次 rollout 合法。PUCT 选择用 `Q(s,a) + c_puct * P(a|s) * sqrt(N_avail) / (1 + N(a))`。

c_puct = 1.4，Dirichlet noise `alpha=0.3, eps=0.25` 只在根节点注入，温度 tau=1 前 15 步之后 tau=0。

叶节点评估是 AlphaGo 模式的 rollout-network 混合：`leaf_v = lambda * V_net + (1-lambda) * V_rollout`。lambda 在训练过程中从 0 线性退火到 lambda_end（当前 0.8），前期纯 rollout 兜底搜索质量，后期网络主导。prior 同样支持 uniform 和 network 的混合退火。

虚损失（virtual loss）让单 worker 内并发多条 rollout，实测提速 1.94×（nw=1 par=4）。

推理架构：每个 worker 进程只跑 MCTS 树和 env.step，网络 eval 通过 Unix pipe RPC 调用独立的 inference server 进程。server 动态 batch ≤ 32 个 eval 请求，max_batch_timeout=3ms。主进程独立跑 training loop 和 arena/gauntlet。worker 见到的是 stale weights（当前配置约落后主进程 10-30 局）。

## 6. 训练循环

自对弈生成 (state, pi_mcts, z) 轨迹存入回放 buffer（容量 50k）。训练线程独立采样 mini-batch 做 value MSE + policy CE + L2 的梯度下降。每 10 个 train step 推送新 weights 到 inference server。奖励纯终局 ±1，局中步骤没有 reward shaping。

每 100 局做一次 arena 评估（challenger 40 局 vs champion），胜率 ≥ 0.55 替换 champion。每 500 局做一次 gauntlet（固定 matchup 对决 mcts_50 / mcts_100 / mcts_200 / random 共 80 局），这是**绝对强度参考点**，不因训练分布变化而漂移。

## 7. 领域随机化

`ScenarioConfig` 支持两种模式：固定模式（team_0/team_1 两个固定阵容）和随机模式（`char_pool` 加 `team_size`，每局自对弈采样一对阵容）。采样保证队内无重复（`rng.sample` 无放回）和 `allow_mirror=False` 时两队不同（即 `sorted(team_0) != sorted(team_1)`，允许局部重叠）。跨队重叠允许，因为 mirror match 当前有一个已知 bug（见第 14 节）。

arena 和 gauntlet 仍用固定 team_0 / team_1（非 mirror），作为跨 run 可比的强度参考点。

## 8. 骰子机制

AP 早期作为"万能骰"的退化情形，后期上了完整 8 种骰子（7 元素 + 万能）。费用分三种原子（同色 / 无色 / 特定色）和三种结构。支付枚举 engine 侧在 `cost_payment.go` 做，支付结果作为 8 维向量进入观测，dice_combo_proj MLP 投影到 d_model。对手骰子数量公开、具体分布私有，确定化采样 multinomial 分布条件于已公开消耗。

## 9. 当前进度和实证数据

C 阶段验证。C1v1 纯网络 leaf eval 失败，gauntlet vs mcts_200 始终 ≤ 5%。诊断：IS-MCTS + random-init 网络 value 对 random 胜率 20%，同一引擎换成 random rollout value 胜率 90%——问题不在搜索，而在 d_model=64 容量下网络 value 是纯噪声，用来做 backup 反而比 random rollout 差。

C1v2 lambda=0 纯 rollout 对照成功，vs mcts_200 在 g500-g1000 达 40-50%，确认管线和搜索引擎本身 work。

C1v3 固定 lambda=0.3 失败，无明显改善，因为初期网络噪声通过 30% 权重毒化搜索。

C1v4 lambda 退火 0→0.8 over 1500 games，跑到 g1000 时 vs mcts_200 达 45%（g300 10% → g500 25% → g1000 45% 单调上升）。训练管线 work 得到验证。**但**发现：C1v4 champion 对 hook token 扰动完全麻木（用 `tools/probe_numeric_sensitivity.py`：counter values 扰动 value 从 -0.99 变到 +0.97，hook token 扰动 value 完全不动）——网络学到了"忽略 hook channel"的捷径。根因：C1v1-v4 默认配置都是赤蝶 vs 赤蝶单角色 mirror，所有局的 hook 集都一样，hook channel 信息熵为零。

当前进行中的是 C1v4 的修复 run（内部代号 F）：5 个角色随机采样，team_size=1，allow_mirror=False，500 局先跑。到评审撰写时 g220+，arena g100 wr=0.85、g200 wr=0.625 两次都换章，loss 稳定，lambda 已退火到 0.11。预期 6 小时后完成。完成后会用同样的扰动脚本测新 champion 是否对 hook channel 有响应。

## 10. 性能实证

tools/mcts_player.py 纯 UCT 场景 rollout 占 93.7%。训练场景（F run，5 角色，lambda≈0.1）实测 profile：eval RPC 73.7%（28ms/call），random rollout 16%（6ms/call），env_query/env_step/determinize/restore 合计 5%。

eval RPC 的 22-28ms 里，pipe 往返 + pickle 开销 <0.5ms（拆解 bench 证实），纯 torch forward 占绝大部分。batch scaling 接近线性（batch=16 耗时 ≈ 16 × batch=1），batch 不摊薄。d_model=64 在 MPS 上 3-4× 慢于 CPU（kernel launch overhead 主导小 matmul）。d_model=128 还没测 MPS。

吞吐对比：C1v4（单角色 mirror）110 games/hr，F（5 角色）46.5 games/hr。慢 58% 的原因：每局步数从 21 涨到 33（多角色游戏更丰富不速决）+ n_active_hooks 从 130 涨到 400+ 让 HookEncoder 变重。都不是实现 bug，是场景本质。

---

# 可能被挑战的技术选型 + 预先理由

## Q1：为什么 MCTS 用 Python 而不是 Go？Go 更快

Python MCTS 的 ctypes 往返 5-15 μs 一次看似很多，但实测 profile 显示 tree descent 的 env_step + env_query 合计只占 5%（F 训练场景）。真正主导的是网络 eval RPC（73.7%），它在 Go 化 MCTS 后还是要跨语言调 Python/torch。

L1 Go 化（只把 random rollout 移进 Go）的收益实测估算：rollout 部分最多 50× 加速，但 rollout 只占 16%，整体训练加速 1.15-1.30×。工程成本估 1 天 + Go ↔ Python 对齐测试。ROI 不突出。

如果未来 eval 瓶颈解决（MPS 有效 / 网络轻量化）、rollout 占比显著上升，再评估 L3 全树 Go 化。短期不值得。

## Q2：为什么 IS-UCT 而不是 PIMC（perfect information Monte Carlo）？

PIMC 让 MCTS 在 rollout 中能看到对手手牌，有已知的"透视偏差"——训练信号污染，agent 学到的是信息完整下的最优策略，在真实部分可观测下性能退化。

IS-UCT 单树 + N_avail 是文献标准方案（Cowling 2012）。智能体自身动作在不同确定化间合法性稳定（自己手牌自己可见），只有对手节点需要处理合法性过滤，实现上大幅简化。我们的测试基准（`tools/mcts_vs_policy.py`）在 C1v4 前用 PIMC 200 rollouts 对 1500 iter PPO 战胜 117-3。但 PIMC 是对付训 PPO 的基线工具，不是训练时的主算法。

## Q3：lambda 退火 0→0.8 不是标准 AlphaZero

标准 AZ 是纯网络 leaf eval。C1v1 实证失败：d_model=64 random init 网络的 value head 输出对 random 胜率 20%（劣于 50% 随机基线），同引擎换 random rollout value 达 90%。网络 value 做 backup 毒化搜索。

AlphaGo 原论文（Silver 2016）本身就是 rollout + network 的 λ 混合（`λ = 0.5` in practice），不是纯 AZ。AZ 是后来 Silver 2017 在 d_model 大到几百兆参数时才能纯网络 work。我们目前 d_model=128，在 single-machine M 系列 CPU 上训练，需要 rollout 兜底。退火是一个明确的实验变量，C1v2/v3/v4 三个消融已经定位 lambda 策略的正确范围。

## Q4：d_model=128 太小，为什么不用 >= 512？

单机 M 系列 CPU + Python 推理环境。bench 显示 d_model=128 batch=4 单次 forward 22-28ms（F 实测），batch scaling 近线性不摊薄。d_model=256 估计 4× 耗时。训练吞吐会从 46 gph 掉到 10 gph 以下，每次 C 阶段实验时间从 12h 变 48h，迭代速度不可接受。

MPS GPU 在 d_model=64 时因 kernel launch overhead 3-4× 慢于 CPU。d_model=128 拐点还没测，如果 MPS 有效会考虑升到 256。评审完后第一个待跑的 bench 就是 MPS vs CPU @ d_model=128。

## Q5：为什么只做 L1 卡池 + 单角色 mirror 那么久？

这是 C1 验证运行的设计意图——**验证训练管线，不是训强 agent**。C1v1-v4 跑的都是最简场景，目的是定位 lambda 退火策略、arena/gauntlet 机制、inference server 是否 work。

场景退化确实导致 C1v4 champion 无法泛化（G3 扰动实证），这是被预料到的——但**验证管线的目标达成了**。F run 是把场景推到 5 角色随机，同时拿 hook channel 扰动实验做可验证的对照。

这是分步实验方法论，不是拖延。

## Q6：每局构造新 env 的 DSL 加载开销

实测 env 构造（含 DSL 加载 + 拓扑排序 + bind_char）约 200ms。每局 33 steps × 约 9 秒每步，构造占比 <1%。不是瓶颈。

真实瓶颈在每步决策的 eval RPC（73.7%），这和 env 构造完全不相关。

## Q7：单机异步训练 + stale weights 的 off-policy 污染

Lc0（国际象棋 AlphaZero 开源实现）和 ELF OpenGo 的工程经验：stale 100+ 局仍然收敛。AZ 算法本身不依赖 weight version——终局 z 是实际胜负结果，不是网络预测；MCTS visit distribution 依赖当时 worker 见到的 weights，但 visits 本身是 on-policy 的（对当时 weights 而言）。训练目标 (z, pi_mcts) 因此没有系统偏差。

我们的 stale 上限 10-30 局，在 Lc0 安全区内。这不是算法近似，是标准工程实践。

## Q8：DSL 用 Lua 子集是否过度工程？

游戏规则需要条件分支（if/elseif）、局部变量、闭包捕获 slot-aware 的角色代理。纯 JSON 表达不了条件。Python 会带 GIL 和沙箱复杂度。

我们的 Lua 解释器是手写 AST 执行器（约 1200 行），只实现 6 个语法结构（local/if/return/arith/table/function），拒绝循环和 pairs/ipairs，全程可审计。不用 LuaJIT 不引入 C 依赖。跑一个 DSL 文件几毫秒，远快于 Python 启动子解释器。

## Q9：Hook tokenization 真能让网络学到规则？G3 实证反例

这是**已知未完全验证的假设**。C1v4 G3 扰动实证显示网络对 hook channel 麻木。我们的解释是"场景退化导致 hook channel 信息熵为零，网络学到 ignore"——F run 是验证这个解释对错的实验。

如果 F run 完成后新 champion 对 hook 扰动仍麻木，就说明阵容随机化不够，需要更强随机化（card_pool 混合、数值扰动、team_size > 1），或者 HookEncoder 架构本身有问题。我们对这个假设没有盲目自信。

这是诚实的开放问题，不是已结论。

## Q10：为什么 arena/gauntlet 不跟训练一起随机化？分布不一致

**主动选择**。arena 的目的是"新网络比旧网络强不强"的相对强度测试，gauntlet 的目的是"绝对强度对比固定基线"。两者都需要**跨 run 可比较**。如果 eval 分布本身每局随机，arena 和 gauntlet 的数字会因采样方差漂移，两次 run 的 gauntlet vs mcts_200 数字不具可比性。

代价是 eval 分布 ≠ train 分布。缓解：如果未来想做覆盖率 eval，可以加 round-robin（每个 matchup 跑 N 局取平均），而不是每局随机。但这是后续工作，不在 C 阶段关键路径。

## Q11：为什么不做 MuZero（learned dynamics model）？

MuZero 主要解决 env 不可访问或成本高的场景（Atari、复杂机器人）。我们的 env 是 Go 引擎里完全可访问的确定性状态机，`snapshot/restore` 8μs O(1)，根本没有必要学 dynamics model。AZ 的算法优势就是直接用真实 env 做 rollout，不引入 world model 的学习成本和偏差。

## Q12：Mirror match hook 重复注册 bug 的修复优先级

已知 bug（任务 #152）：buff 文件（如 `赤蝶_蝶火.lua`）的 hook 在 mirror match 下注册两次，某些 filter 写得不够严时两份都触发，效果翻倍。

当前规避：`allow_mirror=False` + 跨队重叠也允许；arena/gauntlet 的固定 matchup 是赤蝶 vs 墨客（非 mirror）。训练主线完全绕开 bug。

修复方向选定"dynamic hook 架构"（hook 绑 counter，counter 值控制激活）而不是表面 per-owner filter 补丁。预计 3-5 天实施，但**不在 C 阶段关键路径**，F run 完成后才评估是否动。这不是遗漏，是显式推迟。

## Q13：Web UI 为什么在算法未成熟时就上线？

Web UI 的两个模式（replay 回放 + live human-vs-agent）都直接服务算法验证：
- Replay 模式让我们能逐步查看 agent 决策、attention、policy、value，这是对 AZ 抽象训练指标的人类定性检查
- Live 模式让人类玩家对 agent 做图灵测试，发现 agent 是否在做合理行为

两者都是算法诊断工具，不是产品功能。实施的是 FastAPI + React 最小栈，估 2 周工程，没占用算法推进时间。

---

# 当前主要未解问题

1. **F run 完成后 hook channel 能否被激活**：这是最关键的未验证假设。结果二元——如果激活，D10 领域随机化验证通过，项目架构基础稳固；如果仍麻木，需要重新审视 hook tokenization 的有效性或升级随机化强度。

2. **退火 lambda 在 5 角色场景能否迁移**：C1v4 单角色 mirror 下退火 work，但 5 角色场景 game 更长、state 空间更大，网络 value 可能需要更长时间 warm up。F run 观察。

3. **MPS GPU 在 d_model=128 是否可用**：影响 eval 瓶颈能否在不重构网络的情况下优化 20-30%。F run 后独立 bench。

4. **n_counter_slots=1832 对未来 team_size>=2 或 6 角色扩展是否够**：MVP 数字，未来可能撞 obs 维度上限，需要重新标定。

5. **team_size > 1 的阵容是否暴露未知 engine bug**：mirror match hook 翻倍之外可能有其他 team_size 相关的边界条件。F run 定位是 team_size=1 规避这个风险。

---

# 可交付证据

- 代码库：`gicg_engine/`（Go 引擎 + Lua 解释器），`training/`（Python AZ stack），`data/`（DSL 内容）
- 设计文档：`docs/az/`（13 项 AZ 决策 + 架构设计）、`docs/decisions/`（引擎决策）、`docs/engine/` `docs/dsl/`（规范）
- 实证：`docs/az/evidence/`（bench + MCTS vs PPO 可行性探测），`docs/az/c1_postmortem.md`（C1v1-v4 完整复盘 + G3 扰动诊断）
- 训练数据：`artifacts/`（所有 run 的 metrics.jsonl、checkpoints、replays），每个 run 以 `YYYYMMDDHHMM_<label>` 命名
- 测试：Go 端 `gicg_engine/tests/`（约 40 个）、Python 端 `training/tests/`（138 个）+ `gicg_env/tests/`。

评审建议先读 `docs/az/README.md` → `docs/az/decisions.md`（13 项决策） → `docs/az/c1_postmortem.md`（验证历史）。

---

# 12. Post-F hook gradient bug 复盘 + 六项网络修复（2026-04-17 晚）

## 12.1 bug 定位

F run 完成后按 Section 9 流程跑 `tools/probe_numeric_sensitivity.py`，发现新
champion 对 hook token 扰动完全不响应，和 C1v4 的麻木行为一样。如果单角色
mirror 的 shortcut learning 解释正确，阵容随机化后应该至少有部分响应——
结果是 0 响应，异常。

写 5 级架构诊断 `tools/diag_hook_path.py`：
1. hook_emb 置零 vs baseline 输出完全一致 → 网络不用 hook
2. HookEncoder 单元 test：两个不同 hook 输入输出都是 0 向量 → encoder 坏
3. 训练前后权重对比：hook_encoder 所有参数 Δ_L2 / init_L2 = 100%（p ≈ 0，所以 p-init ≈ -init，norm 相等）
4. 梯度流测试：hook_encoder 参数 grad=None
5. CrossAttention weights：对 hook 方向均匀分布（满熵）

**直接查参数值**：HookEncoder LayerNorm weight 初始化 1.0，当前 3.87e-39。
指数衰减到零。

## 12.2 根因

训练路径的 hook_emb 来源：

1. worker 在 game_start 发 static_obs 给 inference_server
2. server 在 `encode_static_tensors` 的 `with torch.no_grad()` 下算 hook_emb
3. server 把 hook_emb `.detach().cpu().numpy()` 返回给 worker
4. worker 把这份 numpy hook_emb 存进 trajectory 的 game_static
5. trajectory 进 replay buffer
6. 训练 train_step 从 buffer 拿出 numpy → 变回 tensor → 喂 `ActorCritic.forward` 的 `hook_emb_cached` 参数
7. `forward` 内 `hook_emb = hook_emb_cached`（直接用）
8. **整条路径 hook_encoder 不在 backward graph 里**

梯度 → hook_encoder 参数永远是 None。AdamW 的 weight_decay 仍然每步乘
`(1 - lr·l2_coef)`。参数指数衰减到 0 后 encoder 输出恒为 0。

## 12.3 修复

**hook gradient 修复**（最核心）：
- `game_static` 存**原始 hook tokens**（`hook_types, hook_values`）而不是预编码 hook_emb
- `Agent.forward_batch` 从 batch 取 tokens，**每次 forward 前重跑 `hook_encoder` with grad**
- Inference 快路径（worker 的 MCTS leaf eval）仍然用 server 侧的 no_grad 缓存 hook_emb（性能不退化）

这个修复顺手发现了其他 5 项问题，一并修：

| # | Issue | 修复 |
|---|---|---|
| A | `az_losses` L2 正则惩罚所有参数（包括 LayerNorm weight 和所有 bias） | skip `dim < 2` 的参数 |
| B1 | CounterEncoder 按 `counter_values != 0` 过滤丢弃真实 counter 的 value=0 状态（破盾、解冻、AP 归零等） | 用 static obs 的 `min/max` 构造 `active_slot_mask`，按它过滤 |
| C | CounterEncoder 里 `.item()` 触发 batch sync（每 forward 一次） | `int(amax.clamp_min(1))`，on-device，单 sync |
| D1 | Policy head 的 `state_vec` 不含 `hook_pool`（原注释说避免 pointer-net degeneracy），导致 policy 对 hook 内容只能通过 action_emb gather 间接感知 | `state_vec = concat(counter_pool, hook_pool, card_emb, meta_emb)` 4·d，和 value_head 对称 |
| E2 | CardEncoder `(tok + count_emb) * counts` 把 count 信号双重放大 | `tok + count_emb`，然后 mean pool on count>0 |
| F | HookEncoder 硬编码 `dropout=0.0`（cross_layers 有 dropout 但 HookEncoder 不跟随） | 构造器加 dropout 参数，ActorCritic 透传 cfg.dropout |

## 12.4 验证

139/139 单元测试全通过（含新加的梯度流回归测试
`test_forward_batch_hook_encoder_receives_gradient`）。

直接实验：构造 synthetic batch 跑 5 次 `train_step`：
- HookEncoder 所有参数 `grad=YES`
- `token_embed.weight` Δ=0.79（init 181.5，0.43% 变化）
- `transformer.layers.0.linear1.weight` Δ=1.11（init 13.07，8.5% 变化）
- LayerNorm weight Δ=0.034（init 11.3，0.3%）

这是正常训练动态，**不再是权重衰减到零**。

## 12.5 对 Section 9 "未解问题" 的重新评估

| 原问题 | 当前状态 |
|---|---|
| F run 完成后 hook channel 能否被激活 | **在 F run 的 ckpt 里永远不能**（hook_encoder 权重 ≈ 0）。C1v6 是第一个公平测试 |
| 退火 lambda 能否迁移到 5 角色 | 管线还是 work 的（F run arena 4/5 换章，loss 稳定），独立于 hook channel |
| MPS GPU d_model=128 | 未变，C1v6 跑完可测 |
| n_counter_slots 对扩展是否够 | 未变 |
| team_size ≥ 2 的 engine bug | 未变 |

新增未解问题：
6. **C1v1 的 "d_model=64 不够" 归因是否仍然成立？** 在 hook_encoder 死的前提下，当然 value head 拿不到泛化信号。修复后重审这个诊断。
7. **所有 F 前 ckpt 价值**：作废。没有任何 ckpt 有可用的 hook_encoder 权重。保留作为"管线能跑通"的证据，不做基线对比。

## 12.6 架构审计其他发现（已决策，部分延后）

同批审计发现但没立即修的问题，记录如下以防遗忘：

- **E**（CardEncoder count 加权）：C1 场景是 L1 only 卡池，count 扭曲不明显；扩到 L2+L3 前必修。修复已做（E2），记录作为"已修 but 仅在 C1 场景免测"
- **D2 升级路径**（`state_q` 对 hook_emb 做 attention pool 代替 concat）：只有 C1v6 跑完发现 D1 还不够时才做。Memory 记录 `project_d2_state_hook_attention.md`
- **任务 #152 dynamic hook 架构**：mirror match hook 重复注册 bug 的正式修复，B 方案（hook 绑 counter 按值分发）。未实施，C1v6 用 `allow_mirror=False` 绕过

## 12.7 对评审材料的影响

本次 bug 发现对 Section 4.3（"反 ID 设计的已知未验证假设"）和 Section 7（"当前验证状态"）的关键修订：

- 原文："C1v4 G3 扰动显示网络对 hook channel 麻木。F run 是验证阵容随机化能否激活假设的实验"
- **修正**："C1v4 和 F 的扰动结果都指向 hook_encoder 梯度断 bug（训练基础设施问题），而不是 shortcut learning（算法问题）。修复后的 C1v6 是首个公平测试"

这不是算法失败。是算法从来没被正确训练过。
