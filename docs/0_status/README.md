---
last_updated: 2026-09-22
status: LIVE
---

# 当前状态

**56 已授权使用。** 授权持续到用户明确取消，包含训练、评估和其他高性能操作。当前没有活动远端任务。

当前活动目标：在保持零样本/少样本泛化能力的基础上，稳定战胜 F1-D2。**尚未完成。**

## 当前研究结论

| 路线 | 最好已确认结果 | 判读 |
|---|---:|---|
| executed warmup + RL16 | 原生约 42–45%，heldout 约 40–43% | 当前最强已确认基线，未过 50% |
| 从零 ExIt z | g225 argmax 3.6%，MCTS16 4.5% | 机制成立，强度不足 |
| 无锚 RL16 热启动 ExIt | ep256 argmax 23.2%，MCTS16 15.0% | 明确退化 |
| 锚定 ExIt beta=0.3 | argmax 34.1%，MCTS16 30.0% | 对配对基线无明确收益 |
| 锚定 ExIt beta=1.0 | 12 局、797 transitions、32 updates | 训练切片过短，不作算法结论 |
| RL16→AZ 参数移植 | 普通决策 argmax 一致率 71% | 非行为等价，停止作为主线起点 |
| 反事实重骰教师 | 32 根平均配对收益 -0.0104，95% 区间 [-0.0933, +0.0725] | 资格未通过，暂停 adapter 训练 |

数据扩容、模型容量、DAgger、追加 RL、后果残差、去锚、事后 value head 和三种推理时搜索均未突破目标。端到端 ExIt 已暂停，只有搜索教师先证明独立收益后才可恢复。当前主路线仍是 [D2 反事实恢复](../3_plans/cards/d2_counterfactual_recovery.md)，但直接反事实教师在 32 根资格评估后仍未决，当前不进入 adapter 或联合训练。

## 当前工程状态

- 当前发布基线为 `v0.3.2`，分支 `dev`，本地提交尚未 push。
- `v0.3.2` 已通过 Go 引擎测试、训练测试、环境与 Web 后端测试、前端 lint/生产构建和 diff 检查。
- `ref/genius-invokation` 是独立参考包，未安装其 `gitcg` 绑定，不计入项目测试。
- 当前本地源码指纹：`dbb7459104dac9f2cdd1cfe860cdd3b924ab76b18fb68805c2f24f56d879f51f`。
- 本地结构拆分已改变源码指纹；beta=1.0 checkpoint 生成于拆分前。
- 56 已确认无活动 Python 进程。run 000084 已停止并保留产物，本地副本已完整拉取。
- 每回合正常重掷已进入引擎；旧 checkpoint 未在该环境中训练，既有强度结果需要在当前规则下重新评估。
- Web 支持选择任意可加载 checkpoint、记录完整对局，并在棋盘内完成目标、骰子支付、调和和重掷选择。

## 下一关口

1. 固化公开牌表来源，并实现后手重骰根的隐藏骰面后验。
2. 重新设计低方差候选选择；现有 8 次发现预算未建立 teacher gain。
3. 在全新根状态和验证种子上重新进行教师资格评估。
4. 只有教师通过后，才训练冻结普通路径的 reroll adapter，再进入分层 replay 的语义 DMC 恢复。
5. 只有新环境恢复基线建立后，才进入多 seed 和 heldout 验证。

## 长期目标

产品方向仍是最新正式服七圣召唤 PvE 决策辅助工具，并积累可复现研究证据。当前阶段仍是模拟环境、规则表达和训练方法验证，不是正式 PvE 产品验收。

## 入口

- [接手清单](../HANDOFF.md)
- [暂停交接](../HANDOFF_PAUSED.md)
- [项目规约](../../openspec/project.md)
- [ExIt / AZ 协议卡](../3_plans/cards/exit_az.md)
- [D2 反事实恢复路线](../3_plans/cards/d2_counterfactual_recovery.md)
- [随机规则变体协议](../../tools/rule_validation/VARIANTS.md)
