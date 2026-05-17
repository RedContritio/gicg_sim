# AlphaZero migration — top-level decisions (D1-D14)

**Status:** Archived (历史 ADR, migrated from `docs/2_decisions/adr-0005-az_decisions_d1_d14.md` at P1-T1)
**Original date:** 2026-04-14 (D1-D11 初稿), 2026-04-18 (D10 状态更新), 2026-04-23 (D14 补记)
**Original status:** Accepted (D1-D13);D14 Accepted then Deprecated (2026-04-21)
**Supersedes:** —
**Superseded by:** —(部分决策被 ADR-0008/0009 实证调整;本 ADR 仍是 AZ stack 决策的 source)

## Why

截至 2026-04-14,项目运行基于 per-size-pool ELO 门控课程 (phase0-5) 的 PPO 自对弈。组合栈下首次训练
(`202604141523_p0p1_minrew`) 干净通过 phase0a→phase1a,但 **phase1b 约第 150 iter 持续回归**,
Δ 第 170 iter 跌至 -289。各指标(`val_ret_corr` / `v_loss` / `clip_frac`)单看健康,策略无法恢复。

**一次可行性探测使方向无法辩护**:200 rollout 纯随机 UCT player 在三场景以 117-3 击败 phase1a
策略(1v1 L1 / 1v1 L1+L2 / 2v2 L1+L2,每种 40 局)。纯搜索 + 0 学习组件 = 主导 1500 iter PPO 训练。

**结论**:基于搜索方法绝对优势;PPO stack 与双人不完美信息零和博弈架构不匹配;"阶段过渡崩溃"
是单 agent PPO 在变化游戏设置下无法维持稳定自对弈均衡的症状。本 ADR 记录 2026-04-14 从 PPO 迁移到
AZ 风格 MCTS + 神经网络协同训练的决策。

## What

14 个决策(D1-D14):

- **D1** MCTS 在 Python 中实现(不 Go;A:迭代快,有 ctypes 开销)— 后被 [`../0004-is-mcts-migration/`](../0004-is-mcts-migration/) 实证修正(team_size=2 让 L3 Go 化 ROI 翻)
- **D2** IS-UCT 单棵树 + N_avail 簿记(Cowling et al. 2012)
- **D3** 单网络共享主干 + 共享 value head + 各阶段独立 policy head(战术 / 构牌)
- **D4** 无对手池,始终与当前网络自对弈;多样性来自 MCTS 探索(Dirichlet + 温度计划)
- **D5** 纯终局奖励 ±1,无 reward shaping;`GicgEnv.step` 签名变 `(obs, done, info)`
- **D6** 纯 AlphaZero,随机初始化 + bootstrap 监控 + 升级方案(Dirichlet ↑ / D13 模式 B / heuristic rollout / 监督注入)
- **D7** 骰子机制(MVP 起步延后,现已端到端 ship — `dice.go` + `cost_payment.go` + Dirichlet 骰子采样)
- **D8** 基于特征的卡牌/角色嵌入,可配置观察维度;特征 MLP 跨实体共享(零样本泛化)
- **D9** `CardPoolSpec` 协议(SharedFixedPool MVP / UniformFromPool 中期 / BayesianFromPlayHistory 长期);引入 `max_copies`
- **D10** 领域随机化:自对弈每局随机抽样队伍 + 卡牌;`disjoint_teams=True` 防 #152 hook 双注册。**已实现并通过 C1v7 验证** (argmax vs mcts_200 = 0.45,2026-04-18)
- **D11** 构牌作为未来阶段(`PhaseDeckbuild` + `deckbuild_policy_head`),MVP 不实现但必须保持开放
- **D12** MCTS 决策粒度 = 复合游戏动作,**不做抽象**(GICG 机制路径依赖);`MAX_ACTIONS` 128→256;不做转置
- **D13** 通过搜索深度 argmax 比较发现连携 (`[50,100,200,400]` 检查点),延后/可选
- **D14** ExpandUnionK(r003) **(Deprecated 2026-04-21:被实证否决,见 memory project_expand_union_k;详 design.md retrospective)** — 只覆盖 dice 维,D1 <20% 触发场景,净负 0.05

## Affected specs

- `training-architecture` (P1-T2/T6 抽 AZ stack SHALL 时 backfill)
- `paradigm-az` (待建)
- `engine-dice` (D7)
- `engine-domain-randomization` (D10)
