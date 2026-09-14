# v7 开发验收记录

2026-09-11。本轮验收结构表达与训练接口，不评估策略强度。

- Go engine 所有包、MCTS、Go actor/socket/shared-memory 检查通过；actor 的通信测试在允许本机通信的环境重跑通过。
- 新引用/实体测试通过：空值、未知定义拒绝、原始引用编号替换、唯一/共享技能归属、支援位置与年龄、天赋槽位、静态引用范围。
- 实体相关 Go race 检查通过。
- Python 实体/来源/静态布局专项 12 passed；CFR 网络/训练/reservoir 50 passed；修改涉及的 CFR 采样/回放专项 66 passed；工具相关 66 passed。
- 五范式完整 smoke：首轮 8 passed、2 failed；BC 修复测试夹具后单独通过，DMC 在源码稳定后重新训练及恢复通过。合计 10 个 smoke_full 用例均有通过记录。CFR 完整 driver 仍使用既有 smoke stub，不代表生产 CFR 训练质量。
- BC 失败是测试夹具直接写 NPZ 缺少 provenance，修复为与正式生成入口共用 save_dataset；没有修改生产来源校验。
- DMC 首轮恢复因运行期间源码改变被 fingerprint 校验拒绝；重跑从新权重开始，恢复后达到 5013 frames。未放宽来源检查。
- 广域 Python 回归首轮在手动停止前为 1181 passed、6 skipped、1 failed；唯一失败来自创建中的 OpenSpec 目录缺少 proposal/tasks。补齐后索引专项通过。广域重跑的耗时尾部主动停止，不声称全套 Python 测试已完成。
- OpenSpec 索引、修改文件格式检查通过。

v7 是新的源码快照，保留 v6 冻结文件，不复用其训练产物。测试在临时工作区进行；
未部署 5070 Ti、未启动正式长程训练。

剩余：显式暂停执行帧尚未实现；静态/动态 counter 视角需整链路专项核对；
动作条件实体注意力、公开历史/记忆和学习效果实验仍在后续。
