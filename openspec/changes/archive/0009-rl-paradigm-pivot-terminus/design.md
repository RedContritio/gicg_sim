# Design (retrospective)

## Consequences

### 正面

- **算力释放**:不再投入 RL self-play long runs(节省每 run 1-30h)
- **产品确定性**:BC ckpt 是确定性 production solution,可直接 ship
- **诚实记录**:负面结果作为 paradigm-pivot 文献预测的**第二次实证**(第一次是 PPO Stage 1 撞墙;
  本 ADR 是 AZ 全栈撞墙)

### 负面

- **paradigm-pivot 文档主路径(BC warm-start)被否决** — 文档需 retroactively 标 OBSOLETE 或加注脚
- **MCTS 搜索价值未被 RL 利用** — 即 BC ckpt 不带搜索,纯 argmax;但 inference-time MCTS(BC-as-policy
  + handcrafted value)仍可在 production 加上,作为 BC 的搜索增强(不需要 train)

### 未尽问题

- F1-D2 真的接近最优吗?未做严格 optimal play vs F1-D2 比对(没有 ground truth)
- 网络架构(transformer + hook attention)是否过强 → BC 直接覆盖 F1-D2 + tied-noise reduction = 0.75。
  换小 MLP 会怎样?(无 ROI 探索)
- 跨 element / cross-team 泛化:r009 BC 只在测试角色D mirror 训过;production 用前需在真角色 + 多
  element 上验证 BC 是否泛化

## Tradeoffs revisited

### Verdict

**Self-play RL 在本游戏类(隐藏信息 + 大动作空间 + 短 horizon mirror match + 强 handcrafted baseline)
结构性失败**。F1-D2 dice_greedy 是该类游戏的 near-ceiling baseline,RL 没有比 imitation-of-F1-D2 更好
的策略可学。

Production = BC + 可选 inference-time MCTS;curriculum closed at Stage 3 via BC。

### 后续部分推翻 (ADR-0010)

同日下午 s068 D4 mirror-break probe(asymmetric teams 赤蝶 vs 墨客,Stage 3 1-card)给出 F1-D2 mean
**0.271 ± 0.078** (n=3),vs s064-066 mirror baseline 0.104 → **+0.167 显著超 noise (>2σ)**。意味着
mirror Nash 锁死**部分**贡献了 RL plateau。

**closure "RL 在本游戏类不可救" 命题被部分推翻** — production fallback decision 不变(仍 r009 BC
ckpt),但 algorithm sweep 重新开启;详见 [`../0010-rl-research-reopen/`](../0010-rl-research-reopen/)。

## References

- `docs/2_decisions/adr-0009-rl_paradigm_pivot_terminus.md` (mirror)
- [`../0008-rl-paradigm-pivot/`](../0008-rl-paradigm-pivot/) — 原假设
- [`../0010-rl-research-reopen/`](../0010-rl-research-reopen/) — 同日下午部分推翻
- `docs/4_runs/registry.md` — s064-066, s067, r009, r010-012 数据
- `docs/5_history/r010_az_bc_warmstart_postmortem.md` — r010 失败诊断
- memory `project_az_stage0_3_baselines` — AZ pure plateau 数据
- memory `project_stage3_full_diagnosis` — PPO Stage 3 30+ ablation
- memory `project_rl_paradigm_pivot` — 文献预测,本 ADR 部分证实
