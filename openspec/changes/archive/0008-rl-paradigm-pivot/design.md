# Design (retrospective)

## Consequences

### Greedy 为什么 work(根因分析)

- 稠密 1-ply HP 信号,绕开信用分配
- 不依赖 value head / 不依赖 self-play 稳定
- 状态值高度与 HP 相关 → domain fact 强

Greedy 的明显弱点 = 10% 左右的长程规划决策(combo / 卡序 / 能量管理 / 诱导换人)。

### 验证路径(原计划)

**r009 = P0-1 单点 BC warm-start**:
- 48h 生成 50k 局 F1-D2 vs F1-D2 (seed 变化 + 20% F1-D1 探索 opponent)
- BC 训练到 ≥ 80% match rate vs F1-D2 argmax
- Gauntlet vs F1-D2 + mcts_200,目标 ≥ 0.80
- 若 ≥ 0.80 → r010 接 fine-tune;若 < 0.60 → 网络容量不足 / obs 问题先修结构

**r010 = P0-2 + P0-3 组合**:BC ckpt 初始化,接 greedy-rollout MCTS + dense reward 的 AZ 训练,
看能否突破 0.90 ceiling

**成功标准**:r010 vs mcts_200 ≥ 0.95 + vs F1-D2 ≥ 0.55(严格好过 teacher)

**失败标准**:r009 match rate < 0.60 或 r010 regress to greedy → 考虑放弃 ML-centric 方案,转 hybrid
系统(greedy 主路径 + learned exception controller)

### 变更的 AZ 决策

- **D5(纯终局 ±1 奖励,无 shaping)** — 重新评估。长程 + 隐藏信息游戏下文献一致认为 shaping 必要。
  新增 D15 记录
- **C1v2 结果的地位** — 本仓库已证 rollout > net-value,r002-r007 的 λ→1 退火与之矛盾。需 D16 记录
  "什么时候用 rollout vs net-value"

## Tradeoffs revisited

### 后续 closure 命中 (ADR-0009 验证否决)

`adr-0009-rl_paradigm_pivot_terminus` 2026-04-28 实证否决本 ADR 核心假设 "BC warm-start 是 dominant
lever":
- r010 (AZ + BC, n=3):200g self-play 把 BC 0.75 → 0.167 (**-0.58**),warm-start 在 self-play 中失效
- s067 (AZ + multi-card, n=3):多卡复杂度让 RL 更弱(F1-D2=0.0625 vs s064-066 1-card 0.104),plateau
  结构性

**当前 closure**:production = BC alone (vs F1-D2 = 0.75),不再 self-play RL。

下方原 ADR 内容保留作决策历史。本 ADR 提出的 P1/P2 路径未被尝试,在 ADR-0009 中归入 "可选未来研究
方向" (dense reward + greedy rollout leaf eval / MuZero-style learned dynamics / imitation learning
extensions)。

## References

- `docs/2_decisions/adr-0008-rl_paradigm_pivot.md` (mirror)
- `docs/5_history/evidence/rl_literature_survey.md` — 完整文献调研(8+ 工作对比表)
- memory `project_r008_postmortem` — r008 失败分析
- memory `project_greedy_baseline` — F1-D2 基线数据
- memory `project_c1v2_results` — rollout-based 训练成功的本仓库证据
- [`../0009-rl-paradigm-pivot-terminus/`](../0009-rl-paradigm-pivot-terminus/) — closure ADR
