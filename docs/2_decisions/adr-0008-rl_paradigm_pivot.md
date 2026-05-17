# RL Paradigm 转向:纯 end-to-end → 混合(greedy warm-start + dense reward)

> **MOVED to `openspec/changes/archive/0008-rl-paradigm-pivot/`**(2026-05-15,P1-T1)
>
> 本 ADR 已迁移到 OpenSpec change archive:
> - [Proposal](../../openspec/changes/archive/0008-rl-paradigm-pivot/proposal.md)
> - [Design / Consequences](../../openspec/changes/archive/0008-rl-paradigm-pivot/design.md)
>
> 本文件保留至 P1++(`docs/2_decisions/` 全量整理)。期间**只读**;
> 修改请走 `openspec/changes/<new-id>/`(若需修订决策)+ OpenSpec
> change workflow。

---


**日期:** 2026-04-24
**触发:** r001-r008 全失败,greedy F1-D2 = 0.90 vs mcts_200 压过所有训练产出

> ⚠️ **SUPERSEDED 2026-04-28** by [`adr-0009-rl_paradigm_pivot_terminus.md`](adr-0009-rl_paradigm_pivot_terminus.md)
>
> 本 ADR 的核心假设 "BC warm-start 是 dominant lever" 被 r010 + s067 实证否决:
> - r010 (AZ + BC, n=3): 200g self-play 把 BC 0.75 → 0.167 (**−0.58**),warm-start 在 self-play 中失效
> - s067 (AZ + multi-card, n=3): 多卡复杂度让 RL 更弱(F1-D2=0.0625 vs s064-066 1-card 0.104),plateau 结构性
>
> 当前 closure: production = BC alone (vs F1-D2 = 0.75),不再 self-play RL。下方旧文保留作为决策历史。

## 问题陈述

r001-r008 共 8 次训练 run,三种 paradigm(AZ naive、AZ 长程 r007、Deep CFR r008),
全部在 GICG 2v2 fixed team 场景上 stuck 或 collapse。最强 run(r001)= 0.55 vs
mcts_200,**低于手工 greedy F1-D2 的 0.90**。训练相对于"不训"是净负增益。

## 证据

| 方法 | vs mcts_200 |
|---|---|
| greedy F1-D2 dice_greedy(手工 1-ply 加 2-ply minimax) | **0.90** |
| r001 AZ 最强 run | 0.55 |
| r007 AZ 长训 final(collapse)| 0.05 |
| r008 CFR 200 iter | 0.00 |

## 根因分析

### 结构性失败模式(r001-r008 共有)

1. **稀疏终局奖励 × ~300 步 episode** — AZ/CFR 的信用分配链过长
2. **隐藏信息 + IS-MCTS 的 determinization 噪声** — 每 rollout 采 1 隐状态,聚合不稳
3. **大动作空间(20-200 含骰组合)** — regret 分散 / MCTS 分支因子爆炸
4. **Self-play 稳定到退化吸引子**(双方 Switch spam,无进展)
5. **Loss 与 policy quality 脱钩**(r008 strat_loss 下降但 win rate 退化)
6. **冷启动 dead zone** — 从 random init value/policy 都瞎猜,MCTS 传播噪声

### Greedy 为什么 work

- 稠密 1-ply HP 信号,绕开信用分配
- 不依赖 value head、不依赖 self-play 稳定
- 状态值高度与 HP 相关 → domain fact 强

Greedy 的明显弱点是 10% 左右的长程规划决策(combo、卡序、能量管理、诱导换人)。

## 文献调研(8+ 工作,见 `../5_history/evidence/rl_literature_survey.md`)

关键 pattern,按被反复使用的频次:

| Pattern | 支持 | 我们当前 |
|---|---|---|
| **Expert heuristic → IL warm-start** | AlphaStar(Nature 2019 明确论证必要)、Suphx SL 预训、Coac LoCM 冠军 | ✗ 全从 random init |
| **Dense reward shaping for long horizon** | Suphx global reward prediction、OpenAI Five(消融证明必要)、AlphaStar score shaping | ✗ AZ D5 决策改纯 ±1 |
| **Expert heuristic 作 rollout / prior** | Coac(depth-3 minimax)、AlphaGo Lee Sedol(rollout+value)、C1v2(本仓库已证 rollout 胜 net-value 10×)| ✗ 当前 AZ 走 λ→1 路线,纯 net-value |
| **Action abstraction** | Pluribus(14 bet-size bucket)、Coac(两类动作模拟)、AlphaStar hierarchical | ✗ 20-200 full payment fan-out |
| **CFR-based subgame search 替代 MCTS** | Pluribus blueprint+real-time、ReBeL PBS、Student of Games GT-CFR | ✗ 用 AZ 原版 PUCT MCTS |
| **Oracle guiding**(训练看隐状态,推理退火 dropout)| Suphx(Microsoft Mahjong) | ✗ 只看 observable |

**命中率 0/6。** 我们在做的就是文献明确论证"在这种游戏上不行"的配置。

## 决策:Paradigm 转向

**弃:** pure self-play from random,pure AZ with λ→1,pure Deep CFR

**采:** 渐进式混合架构,优先 P0 三件套。

### P0(立即可做,低风险)

1. **Greedy behavioral cloning warm-start**
   - 用 F1-D2 dice_greedy 生成 50k-100k self-play 轨迹(带探索温度)
   - 预训网络 policy/value 到 match F1-D2 argmax(≥ 80% 对齐)
   - 下限已知 = F1-D2 本身(0.90 vs mcts_200)

2. **Dense reward shaping(HP delta)**
   - 原 AZ D5 决策(纯 ±1)需重评估
   - reward = 终局 ±1 + λ × (round-over-round 己方 HP - 对方 HP 变化)
   - λ 从 0.3 退火到 0.05 稳态(避免过度依赖 shaping)
   - 理论依据:Suphx / OpenAI Five 的显式消融

3. **Greedy rollout 替代 net-value leaf eval**
   - MCTS leaf 处用 truncated greedy F1-D1 rollout(10-20 步)→ 终局估
   - 替代当前的 `λ·net_value + (1-λ)·random_rollout` 为 `λ·net_value + (1-λ)·greedy_rollout`
   - 本仓库 C1v2 已证 rollout > net-value 十倍差距;r007 collapse 直接来自 λ→1 退火的 net-value 依赖

### P1(中期,架构 + 训练管线变化)

4. **Action abstraction**:`dice_greedy` filter 思想搬进 MCTS/network,logical action 级别而非 full payment,分支因子降 5-10×
5. **Oracle guiding**:训练网络输入加对手 hand/dice oracle feature,退火 dropout(Suphx 架构)

### P2(重型,若 P0-P1 不够)

6. **CFR-based search 替代 MCTS**(ReBeL / Student of Games 路线)
7. **League training**(AlphaStar pool 式,多种 opponent 风格)

## 非决策(已评估但不采)

- **纯 DMC(DouZero 风格)** — 作者本人论证他们的游戏 horizon 30 步,我们 300 步,MC 方差会爆炸,不适配
- **MuZero** — hidden info 下 latent state 不处理对抗性隐藏,论文只在完美信息验证
- **ReBeL 完整实现** — public belief state 在我们隐藏信息组合空间下 intractable,只借鉴思想不照搬

## 验证路径

**r009 = P0-1 单点 BC warm-start:**
- 48h 生成 50k 局 F1-D2 vs F1-D2(seed 变化 + 20% F1-D1 探索 opponent)
- BC 训练到 ≥ 80% match rate vs F1-D2 argmax
- Gauntlet vs F1-D2 + mcts_200,目标 ≥ 0.80(网络接近 F1-D2 级别)
- 若 ≥ 0.80 → r010 接 fine-tune;若 < 0.60 → 网络容量不足 / obs 问题,先修结构

**r010 = P0-2 + P0-3 组合:** BC ckpt 初始化,接 greedy-rollout MCTS + dense reward 的 AZ 训练,看能否突破 0.90 ceiling。

**成功标准:** r010 vs mcts_200 ≥ 0.95,且 vs F1-D2 ≥ 0.55(严格好过 teacher)。

**失败标准:** r009 match rate < 0.60 或 r010 regress to greedy。若失败,考虑放弃 ML-centric 方案,转 hybrid 系统(greedy 主路径 + learned exception controller)。

## 变更的 AZ 决策

- **D5(纯终局 ±1 奖励,无 shaping)** — 重新评估。长程 + 隐藏信息游戏下文献一致认为 shaping 必要。新增 D15 记录。
- **C1v2 结果的地位** — 本仓库已证 rollout > net-value,r002-r007 的 λ→1 退火与之矛盾。需要 D16 记录"什么时候用 rollout vs net-value"。

## 相关决策 / 文档

- `../5_history/evidence/rl_literature_survey.md` — 完整文献调研(8+ 工作对比表)
- memory `project_r008_postmortem` — r008 失败分析
- memory `project_greedy_baseline` — F1-D2 基线数据
- memory `project_c1v2_results` — rollout-based 训练成功的本仓库证据
- memory `project_r007_collapse`(若存在)— λ→1 net-value 导致的 collapse
