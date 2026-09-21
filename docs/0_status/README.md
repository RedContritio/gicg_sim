---
last_updated: 2026-09-21
status: LIVE
---

# 当前状态

**训练暂停，56 禁止使用。** 禁止状态持续到用户明确重新授权；禁止期间不做任何远端探查、同步、训练、评估或进程操作。设备授权不等于自动授权启动训练。

当前活动目标：在保持零样本/少样本泛化能力的基础上，稳定战胜 F1-D2。**尚未完成。**

## 当前研究结论

| 路线 | 最好已确认结果 | 判读 |
|---|---:|---|
| executed warmup + RL16 | 原生约 42–45%，heldout 约 40–43% | 当前最强已确认基线，未过 50% |
| 从零 ExIt z | g225 argmax 3.6%，MCTS16 4.5% | 机制成立，强度不足 |
| 无锚 RL16 热启动 ExIt | ep256 argmax 23.2%，MCTS16 15.0% | 明确退化 |
| 锚定 ExIt beta=0.3 | argmax 34.1%，MCTS16 30.0% | 对配对基线无明确收益 |
| 锚定 ExIt beta=1.0 | 仅产出 ckpt_2431 | 尚未评估 |

数据扩容、模型容量、DAgger、追加 RL、后果残差、去锚、事后 value head 和三种推理时搜索均已证伪或关闭。完整 falsification map 见 [F1-D2 战役总结](../5_history/d2_campaign_20260917.md)，ExIt 全过程见 [ExIt 报告](../5_history/exit_pilot_20260918.md)。

## 当前工程状态

- 分支 `dev`，本地领先 `origin/dev` 15，尚未 push。
- 工作区保留大量未提交的训练、评估、远端同步、Web 和文档改动。
- 2026-09-21 已完成 `v0.3.0` 至当前工作区的累计审查、修复与本地验收：项目 Python 测试 2697 通过、18 跳过；Go test/vet/build、前端 lint/生产构建、Ruff、300 行门禁、OpenSpec 索引和 diff 检查均通过。
- `ref/genius-invokation` 是独立参考包，未安装其 `gitcg` 绑定，不计入项目测试。
- 当前本地源码指纹：`0dff7aef5a6d4f71970c8b7f75977830fa1854d94b9f9d49599b663fcff1ff05`。
- 本地结构拆分已改变源码指纹；beta=1.0 checkpoint 生成于拆分前。
- 56 最后已知无活动训练进程，但其 run 000084 metadata 仍为 `running`；禁止状态下不得重新核实或修正远端。
- Web 已接入 AZ 模型、评估摘要、重掷交互和最少万能骰支付推荐；前端生产构建已通过。

## 下一关口

1. 收口提交边界；工作区若继续变化，重跑与改动相称的本地验收。
2. 等用户明确重新授权 56。
3. 重新授权后优先评估 beta=1.0 的 `ckpt_2431.pt`，不要先同步覆盖旧现场。
4. 只有出现可靠收益，才进入新 seed、多种子和 heldout 变体验证。

## 长期目标

产品方向仍是最新正式服七圣召唤 PvE 决策辅助工具，并积累可复现研究证据。当前阶段仍是模拟环境、规则表达和训练方法验证，不是正式 PvE 产品验收。

## 入口

- [接手清单](../HANDOFF.md)
- [暂停交接](../HANDOFF_PAUSED.md)
- [项目规约](../../openspec/project.md)
- [ExIt / AZ 协议卡](../3_plans/cards/exit_az.md)
- [随机规则变体协议](../../tools/rule_validation/VARIANTS.md)
