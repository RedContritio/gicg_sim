# RL 文献调研:TCG / 隐藏信息 / 大动作空间游戏的成功方案

**日期:** 2026-04-24
**触发:** r001-r008 全失败,需要从文献看 paradigm 失误在哪

每个工作 ~200 字 + 对我们游戏的启示。综合判断在末。

---

## 1. DouZero(Zha et al., ICML 2021)

**Key insight:** 大动作空间 × 隐藏信息 × 长 horizon 上,Deep Monte-Carlo(DMC)比 AZ/CFR 更鲁棒,关键是靠**大规模 parallel actors 压方差**,不靠 tree search。

**架构:** 斗地主(3 人,10^4 量级合法动作,隐藏手牌,~30 步/局)。放弃 MCTS 和 CFR,回到 Monte-Carlo 估计 Q(s,a):每 episode 跑完,用终局 reward 更新轨迹上每个 (s,a)。**创新**:(a) action encoding 把每个合法动作编为 card matrix 喂进 Q 网络,让 Q(s,a) 对未见过的组合动作可泛化;(b) 48 actor + 4 GPU 并行采样、单集中 learner,压住 MC 方差;(c) 纯 self-play from random,无 IL、无 shaping、无启发式。10 天训练超越前代 DeltaDou(2 个月 SL+RL)。

**启示:** DMC 是唯一一个「随机初始化 + 纯 self-play + 无 search」能在大动作空间成功的 case。但它和我们差别大:(1) 斗地主每局 ~30 步,我们 ~300 步(长 10×,MC 方差爆炸);(2) 斗地主 typical legal actions 只有 10-20(我们 20-200);(3) reward 稀疏但短 horizon 下可扛。**直接搬不适合**。

- arXiv: https://arxiv.org/abs/2106.06135

---

## 2. LoCM Competition(Coac 2019 冠军 + arXiv 2305.11814 综述)

**Key insight:** 简化 Hearthstone(LoCM)五届 AI 竞赛中,**纯搜索 + 手工 heuristic 压倒一切 DRL 方案**。与我们 F1-D2 vs mcts_200 = 0.90 的观察完全一致。

**架构:** Coac 冠军 battle phase 用 **depth-3 Minimax + 启发式剪枝**,对手模拟只考虑「attack player / attack monster」两类动作(手工 action abstraction)。draft 阶段 fixed card-value ordering。所有冠军都是 Minimax 或 depth-limited MCTS + 手工 evaluation 的变体;端到端 DRL(如 ByteRL)即使赛内强,也「高度可被利用」。

**启示:** F1-D2 = 0.90 不是个例,是这类游戏的 pattern。Coac 的动作抽象提示我们:**不是所有 200 legal actions 都有实质差异**,按「出牌/切人/结束」大类 + 子类降基数,MCTS 分支因子立刻降 5-10×。

- arXiv 综述: https://arxiv.org/abs/2305.11814

---

## 3. Pluribus(Brown & Sandholm, Science 2019)

**Key insight:** 多人不完美信息游戏中,**离线 MCCFR 只学「蓝图策略」,真正强度来自对局时重新 solve 当前 subgame**。

**架构:** 6 人 No-Limit Hold'em。离线:MCCFR 学 blueprint(仅 pre-flop),使用激进 action abstraction(连续下注离散成 14 个 bucket),状态也 abstract。在线:每次重新做 depth-limited subgame solving,leaf value 用 blueprint 估计 + 4 种「opponent continuation」取最悲观。击败 5 位职业选手。

**启示:** Action abstraction 深度应用的典范。我们 200 legal actions 里很多是「骰子搭配细微差别」,abstract 到 30-50 类能大幅减分支。另:**blueprint-only-pre-flop + 对局中 search** 提示可以**只在开局/换牌学静态策略,对局中 search 主导**。

- Paper: https://www.science.org/doi/10.1126/science.aay2400

---

## 4. ReBeL(Brown et al., NeurIPS 2020)

**Key insight:** 把「state」扩展成 **Public Belief State (PBS)** — 对手对私有信息的概率分布 + 公共观察。在 PBS 上可以像 AZ 一样做 self-play + search,**理论保证收敛到 Nash**。

**架构:** 训练 value net + policy net,输入是 PBS 而非 history。每步做 CFR-based subgame search,用当前 PBS 为根展开,叶子 value 由 value net 估计,内部 CFR 迭代出近似均衡。完美信息特例下退化为 AZ;**不完美信息下用 CFR 替代 MCTS** 作 search backbone。

**启示:** 对「为什么 AZ 在 hidden info 上失败」的最清晰诊断 — AZ 的 MCTS 在 determinized info set 上抽样,同一公共 state 下对手私有信息的 belief 未被显式建模,噪声从这里进。**但 PBS 在我们问题上 intractable**(手牌 × 牌组 × 骰子联合指数爆炸)。**可搬的是思想**:网络输入至少要有对手 hand/dice 分布特征,即便粗。

- arXiv: https://arxiv.org/abs/2007.13544

---

## 5. Student of Games(Schmid et al., Science Advances 2023)

**Key insight:** 同一份代码在 perfect info(Go/chess)达 AZ 水准,在 imperfect info(HUNL/Scotland Yard)达 SOTA,**靠 GT-CFR(Growing-Tree CFR)作 search backbone 替代 MCTS**。

**架构:** GT-CFR 是 anytime 的局部搜索,非均匀展开 subgame,向「最相关未来 state」增长,迭代 refine value 和 policy。Value target 靠 bootstrapping;policy/value net 提供 prior + leaf value,框架和 AZ 同构,只是 search 操作符从「PUCT + backup」变「CFR iteration on growing tree」。覆盖 4 类游戏均 SOTA。

**启示:** 可能是最贴我们场景的学术方案。Scotland Yard 和 TCG 相似(公共信息丰富,隐藏状态,决策分支大)。**但实现难度比 MCTS 高一个数量级**,300 步内存/时间开销会很大。**可分段搬**:value net 以 belief 为输入,不一定完整 GT-CFR。

- arXiv: https://arxiv.org/abs/2112.03178

---

## 6. AlphaStar(Vinyals et al., Nature 2019)

**Key insight:** 大动作空间 × 隐藏信息 × 长 horizon 上,**从随机 self-play 学不出来,IL warm-start 不是加速技巧而是必要条件**。

**架构:** StarCraft II(~10^26 可能动作,部分观测,几千步 episode)。
- Stage 1: 971,000 场人类 replay SL,得到「已比 84% 真人强」的 initial policy,IL 学到多样开局
- Stage 2: League training — 维护 agent 池(main/exploiters/league/past),多 agent RL + population-based training
- Stage 3: IL distillation(KL 正则)防遗忘人类知识

**明确报告:去掉 SL warm-start,RL 从头学不出 grandmaster**。

**启示:** 直接打脸我们 pure self-play。**F1-D2 = 0.90 已是一个很好的 teacher**,用它生成 100k-1M 轨迹做 BC 预训,接 AZ fine-tune。League play 可简化为「池化多种 opponent 类型(greedy/random/mcts_N)」。

- Nature: https://www.nature.com/articles/s41586-019-1724-z

---

## 7. Suphx(Li et al., arXiv 2020)— **最贴我们问题**

**Key insight:** **训练时给 agent 看完美信息(oracle features),推理时渐进 dropout 到只剩 observable**。直接绕开「hidden info 下 value function 不好学」的问题。

**架构:** 日本麻将(4 人,对手手牌/牌山不可见,~50-100 步/局,reward 结构复杂)。三大创新:
1. **Global reward prediction:** 单局稀疏,训预测器根据中间观察预测最终 reward → dense signal(**learned reward shaping**)
2. **Oracle guiding:** 训练时网络输入 {observable, dropout-后的 oracle}, dropout 从 0 退火到 1;训练初期看所有信息学强决策,推理时只 observable,网络被迫 distill
3. **pMCPA:** 推理时做 parametric Monte-Carlo policy adaptation(搜索的轻量替代)

达天凤 10 dan,超绝大多数顶级人类。

**启示:** **本调研中最直接可搬**。我们完美对应 Suphx 三个问题:(a) 隐藏手牌/骰子/牌组 → oracle guiding;(b) 300 步稀疏 reward → global reward prediction;(c) AZ 不 work 可能因 tree search 在 hidden info 下噪声 → pMCPA 替代。**具体可做 C1v8 方向的主打实验**。

- arXiv: https://arxiv.org/abs/2003.13590

---

## 8. OpenAI Five(OpenAI, arXiv 2019)

**Key insight:** **稀疏终局 reward 在 ~20k 步游戏里训不动**,用了非常激进的 reward shaping(每个 XP/金钱/击杀/存活都给奖励),没做 IL warm-start 就是靠 shaping + 大算力硬训出来。

**架构:** Dota 2(5v5,~20k 步/局,连续动作 ~10^6)。纯 PPO self-play,256 GPU × 10 个月。reward function 数十项 shaped term(last hit/kill/XP/gold/tower/alive),对手 reward 相减做 zero-sum smoothing。**消融:只用 win/loss reward 训得慢一个数量级。**

**启示:** **「纯终局 reward 在长 horizon 上不行」的硬证据**。我们 300 步 ±1,r007 长程 collapse 直接符合。可搬:`reward = ±1 + λ·(己方 HP - 对方 HP 的 round-over-round 变化)`,λ 从 0.3 退到 0.05。**AZ D5(纯 ±1)决策需要重评估。**

- arXiv: https://arxiv.org/abs/1912.06680

---

## 综合比较表

| 工作 | IL warm-start | Reward shaping | Heuristic prior/rollout | Action abstraction | Blueprint+search |
|---|---|---|---|---|---|
| DouZero | — | — | — | action encoding | — (纯 DMC) |
| Coac/LoCM | — | —(手工 eval 即用) | ✓(手工 eval = prior) | ✓(两类动作模拟) | 仅 search |
| Pluribus | — | — | — | ✓✓(14 bet size) | ✓✓ |
| ReBeL | — | — | — | — | ✓(CFR subgame) |
| SoG | — | — | — | — | ✓(GT-CFR) |
| AlphaStar | ✓✓(971k replay) | 部分(score shaping) | ✓(league exploiters) | ✓(hierarchical) | — |
| **Suphx** | ✓(SL 预训练) | ✓✓(global reward pred) | ✓(oracle guiding) | — | pMCPA |
| OpenAI Five | — | ✓✓✓(激进 shaping) | — | — | — |

## 反复成功的 pattern

**出现次数 ≥3:**

1. **Expert heuristic 作 prior/rollout/distillation target**(Coac、Suphx oracle、AlphaStar league):**我们 F1-D2 是未使用的最大资产**
2. **Reward shaping 在长 horizon 上不可省**(Suphx、OpenAI Five 都显式论证;AlphaStar 也用 score shaping):**AZ D5 纯 ±1 决策需要重评**
3. **Action/state abstraction 降搜索分支因子**(Pluribus、Coac、AlphaStar):**dice_greedy filter 可以进网络/MCTS 而不只在 greedy player 里**
4. **Search 和 learning 的 divergence**:AZ(MCTS+PUCT)在我们问题上不 work;CFR-based subgame 理论对但实现 10× 重;DouZero(无 search)简单可行但 horizon 不匹配。**先放弃 AZ search,用 DouZero + Suphx 组合作中间 baseline**
5. **Pure self-play from random 只在 DouZero 一处成功**,且其 horizon 和 legal action count 都比我们小。AlphaStar 明确测过,从随机不行。

## 下一步优先级

- **P0(立即)**:F1-D2 BC warm-start(类 AlphaStar)+ HP delta dense shaping(类 OpenAI Five)+ greedy rollout leaf eval(类 AlphaGo Lee)
- **P1(中期)**:Oracle Guiding(类 Suphx)— 训练输入加 opponent hand/dice,退火 dropout
- **P2(对照)**:DMC baseline(类 DouZero),看 search 是否必需
- **P3(重型)**:GT-CFR 或 ReBeL PBS 的 partial 实现(若 P0-P2 不够)

**关键判断:** r001-r008 stuck 不是个例,是「大动作空间隐藏信息长 horizon 游戏 RL」的经典失败。文献给出的解法一致 — **warm-start + reward shaping + abstraction + 合适的 search backbone**,四样我们当前一样没做。优先做 warm-start 和 shaping,再评估是否需要算法层改动。

## 参考资源

- DouZero arXiv: https://arxiv.org/abs/2106.06135
- LoCM 综述: https://arxiv.org/abs/2305.11814
- Pluribus Science: https://www.science.org/doi/10.1126/science.aay2400
- ReBeL: https://arxiv.org/abs/2007.13544
- Student of Games: https://arxiv.org/abs/2112.03178
- AlphaStar Nature: https://www.nature.com/articles/s41586-019-1724-z
- Suphx: https://arxiv.org/abs/2003.13590
- OpenAI Five: https://arxiv.org/abs/1912.06680
