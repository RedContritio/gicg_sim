# 新 session 接手清单

**用户已要求暂停。恢复先读 [暂停交接](HANDOFF_PAUSED.md)，不要自动启动训练。**

当前状态以 [docs/0_status/README.md](0_status/README.md) 为唯一实时入口；本页只描述接手步骤。更新时间：2026-09-14。

周/月级目标、各步验收和待选方案见[执行路线图](3_plans/rule_learning_roadmap.md)。先核对当前关口证据，再安排下一实验，不按日历推定已完成。

1. 读实时入口、[CLAUDE.md](../CLAUDE.md)、[项目目的](../openspec/project.md)。当前目标是随机规则变体下稳定胜过D2，尚未完成。不要沿历史v15/旧卡池实验误续训。
2. 检查`git branch --show-current`和`git status --short`。三项修复已通过[集成验收](3_plans/inference_consistency_repairs.md)，本轮按用户授权提交并压缩合入main；最终分支与提交以Git为准。保留后续工作区改动，不reset/clean，不擅自覆盖远端。
3. 校准残差实验`artifacts/consequence_calibrated_rl_20260914`已完成，等待器34391正常退出；报告已拉回本机同名目录。新快照为`D:/gicg_consequence_20260914`。独立变体初始19.09%、候选21.36%、对照24.09%，尚未达标。先核对结果和所选模型探针，再安排下一轮；不要重启已完成任务。
4. 流程未结束则保持训练源码不变；用户允许56大规模训练/评估及提高并行。流程结束后用`tools.runs._host`/项目pull封装取报告和检查点，不手写SSH/SCP。
5. 核查pipeline记录的source/tool hash、checkpoint SHA、变体catalog SHA、场景/种子/两席位两布局、原始轨迹及聚类统计。不能把挑选后的开发胜率当最终结论。
6. 按[预测后果策略计划](3_plans/cards/consequence_policy_rl.md)接手新格式初始化与残差RL。旧联合RL和三模型凯亚16例探针已完成，尚缺五角色更广泛反事实策略响应；胜率和规则响应均需要证据。未知规则边界单独问用户并记入[游戏内清单](3_plans/cards/in_game_rule_verification.md)。

## 重要约定

- 训练阵容为原生凯亚/迪卢克/芭芭拉/砂糖/菲谢尔；3v3、每队30张随机合法牌；D2是强标准，不需要D3。
- 不保留受污染权重用于当前训练，不改指纹骗过兼容性检查。BC、DAgger和引擎辅助监督不能称纯RL；纯RL是长期独立方向。
- 大规模运算在56；其旧D:/gicg_dev和D:/gicg_goal是历史目录，不随便清理。
- 按需用≤200B的progress查看进度；有完成脚本，不高频读取大日志。跨会话不能依赖聊天内的自动通知仍有效。
- 用户未要求本次停止远端训练；停止聊天、停止训练、提交工作区是不同操作。

## 最小接手提示词

> 阅读 CLAUDE.md、docs/0_status/README.md 和 docs/HANDOFF.md，在当前 dev 工作区接手。先确认56新根D:/gicg_consequence_20260914的consequence_calibrated_rl_20260914状态，不重复启动；保留未提交代码。继续目标：解决学习不到规则的问题，在随机变体下稳定胜过D2。以原始评估与反事实证据判断完成，不依据历史状态或单次开发胜率。

## 历史资料（不代表当前状态）

- [历史交接 1](5_history/handoff_20260914_part1.md)
- [历史交接 2](5_history/handoff_20260914_part2.md)
- [历史交接 3](5_history/handoff_20260914_part3.md)
