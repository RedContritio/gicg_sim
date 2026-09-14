# v8 验收结果

2026-09-11。完成双方视角与 counter 静态绑定对齐，未修改卡牌规则。

| 检查 | 结果 |
|---|---|
| Go engine 全部包与 MCTS | 通过 |
| Go actor、原生 DMC actor、TCP/共享内存运输 | 通过 |
| 新视角/引用/实体 Go race 检查 | 通过 |
| Python 训练与环境回归 | 1226 passed，6 skipped |
| 五范式默认 smoke | 5 passed |
| 完整 smoke：五范式短程训练/保存/恢复及多进程检查 | 10 passed，647.58 秒 |
| 实际五范式混合视角读出及归一化专项 | 7 passed |
| OpenSpec 索引、修改文件格式、diff 空白检查 | 通过 |

广域回归明确排除一个未改动的无上限四层 minimax 用例；具体原因和独立 oracle
见 [verification.md](verification.md)。未把手动停止的首轮回归当作完整通过。

完整 smoke 在生产源码稳定后一次跑完。CFR driver 的完整 smoke 仍采用既有
测试 stub，不能证明生产 CFR 训练质量；实际 CFR 策略和双方 advantage 网络
另外通过了混合 P0/P1 readout 入口核对。

新旧布局不兼容，v7 及更早权重/数据不得继续训练。来源入口保持严格校验；
所有本轮 smoke 产物位于临时工作区。v6/v7 历史实验不能作为修复后学习效果的证据。

本轮只完成视角对齐。尚未实现显式暂停执行帧，也未启动 5070 Ti 正式长程训练。
