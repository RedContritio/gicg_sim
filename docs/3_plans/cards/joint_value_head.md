# 联合训练专用评估头（候选，未启动）

状态：协议草案。动机：推理搜索三变体证伪的共同根因是**没有可用的局面评估
信号**——RL 的 value head 是事后 baseline（冻结编码器、±1 目标、方差削减用途），
1-ply/rollout 搜索拿它当评估器即崩溃（value1p 1.82%）。若搜索/规划要成立，
需要一个**真正训练来评估局面**的 value function。

## 设计草案

- 数据：用 RL16 策略自对弈/对 F1-D2 采集 N 局（如 512 局 × 每局全部决策点），
  冻结 RL16 骨干，只训 value head（或 value 小 MLP 接骨干 state），目标 =
  终局结果（acting 玩家视角 1/0.5/0），MSE。
- 与 baseline 头的关键区别：① 海量标签（每局 ~30-80 决策点 vs RL 的每局 1 条
  优势信号）；② 可选的梯度进入骨干最后几层（联合微调）；③ 训练/留出诊断
  必须报告（R²、校准曲线），验收线：留出集 value 预测与终局结果的相关性
  显著高于 RL baseline 头（参照 `imitation_gap_20260917/` 的 audit_fit 格式
  出 value 版诊断）。
- 通过验收后再测 value1p 搜索（信号若足够，应显著高于 1.82% 的崩溃线；
  合理目标是至少不低于策略 argmax 的 40%+ 水平）。
- 预算：采集 ~30 分钟（16 workers）+ 训练 ~10 分钟 + 诊断/面板 ~20 分钟。
- 风险：即使 value 头训练良好，1-ply 搜索收益仍不确定（策略 argmax 已隐含
  一步评估）；若失败则搜索路线彻底关闭，只剩 AZ 支线。

## 备选：AZ 支线（ExIt）

仓库已有 gicg_mcts（Go MCTS + determinization）、az 范式（配置在
configs/_archived/az_apr/）、Go 侧 MCTSSearch c-export、`_AgentMCTSPlayer`。
**历史结论（docs/5_history/handoff_20260914_part2.md）**：
- AZ 纯自博弈 2026-04-28 关闭：mirror Nash 锁死，plateau 0.06–0.15；
- AZ+BC warm-start 关闭：r010-012 把 BC 的 0.75 摧毁到 0.167（mirror 对手分布
  漂移 + 探索噪声冲洗 sharp policy）；
- 06-12 已定补救方案：**ExIt（搜索+迭代蒸馏）+ 固定对手 OpponentPool**
  （`paradigms/az/paradigm.py:108` 的 `del opp_pool` 换成 DMC 已验证的
  OpponentPool，约 550–700 LOC），`value_target_source=mcts_value` 从未启用，
  是 pilot 必备对照臂；
- 用户 06-11 定义「真正学会」= 能找到 combo 获胜路线，**验收时允许 agent 带
  搜索**——与当前语义策略路线不同，AZ/ExIt 是作者心目中的正解。
属多日至周级工程，启动前先按本卡格式写正式协议。
