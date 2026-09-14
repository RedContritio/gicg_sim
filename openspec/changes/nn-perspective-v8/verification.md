# 视角对齐验收说明

## 独立检查

`gicg_engine/tests/counter_perspective_test.go` 通过 SID→原始 counter 的反查核对
所有有效观测槽位。包含 P0 一角色、P1 两角色的非对称队伍、不同 HP、引用卡牌、
Runtime.Clone、快照恢复和真实技能致死后的强制换人。强制换人时检查 Turn=0、
ActingPlayer=1、observer=1、is_my_turn=0。

`training/tests/test_perspective_alignment.py` 检查静态范围归一化、两种原始视角、
敌方骰子遮罩、乱序 SID 的结构化读出及梯度。还通过正式 paradigm factory
分别实例化 AZ/PPO/DMC/BC/CFR，向其送入混合 P0/P1 batch，在实际 readout 入口
核对角色属性、骰子和存活人数。CFR 检查策略头及双方 advantage 网络。

## 测试夹具修正

旧夹具中的 meta 18 字段更新至 19，新增 observer 使用合法的 0/1，保留真实
观测的严格校验。没有将非法视角猜成 P0。

旧 modifier→value 测试依赖单随机种子差异超过 1e-5。meta 投影维度变化后，
实际差异为 4.67896e-6，modifier 两个标量梯度为 5.31843e-7、3.01959e-6；
独立只读复核确认通路未断。测试改为同时要求输出精确不同和实际 modifier
标量存在有限非零梯度，不更改生产网络以适配随机阈值。

## 广域测试边界

未运行完成 `test_greedy_player.py::TestMinimaxBudget::test_budget_uncapped_equals_old_const`。
它比较深度 4、无节点上限与 1e9 节点预算两次搜索，首轮耗时定位后明确排除。
未改动此用例、greedy 特征或搜索算法；其余训练/环境回归均重新完整执行。
