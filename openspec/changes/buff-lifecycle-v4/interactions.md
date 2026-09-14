# v4 交互与验收

| 场景 | 预期与测试 |
| --- | --- |
| 双方交错产生普通 buff，改变先结束方 | 全局 FIFO 不变；`TestRoundBuffCrossPlayerOrder` |
| 双方交错产生召唤物，改变先结束方 | 先结束方全部先处理，同侧 FIFO；同上 |
| 双方召唤物下一击都致死 | 先结束方胜；`TestRoundSummonFirstEndDecidesLethal` |
| 双方蝶印下一击都致死 | 先产生的印决定胜负；`TestRoundMarksGlobalCreationDecidesLethal` |
| 事件内移除、重建同一个 buff | 新实例不替旧实例执行；`TestRecreatedBuffWaitsForNextEvent`、`TestRoundBuffAgendaDoesNotRunReplacement` |
| 同模板独立层 2/1 回合与 3/2 回合 | 次数分别消耗、分别到期、快照恢复一致；`TestIndependentBuffChargesDurationAndRestore` |
| 两层同一减费效果，第一层已减到零 | 仅第一层消费；`TestIndependentBuffApplicationConsumption` |
| 敌方治疗己方、伤害被己方盾吸收 | 以逸反击目标与奖励均属于持有方；`TestRetaliationOwnerAndTargets` |
| 同文件含多个无关 hook | 仅绑定 hook 进入实例行；`TestBuffObservationUsesInstanceStateAndPreciseHooks` |
| 改内部生命周期编号 | NN 观测不变；同上 |

旧的 v1/v2/v3 回归继续运行。本表不代表所有卡牌组合都已穷尽。
