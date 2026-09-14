# 已覆盖、缺口与初训范围

| 路径/风险 | 依据 | 状态 |
| --- | --- | --- |
| 当前默认配置实际加载的规则 | effect-inventory.json，生产 factory | 无审计问题 |
| 费用/目标及其依赖效果 | current_cards_*、current_rules_*、target_frame_test | Go 回归通过 |
| 连续死亡、分支修改、分支 RNG 与日志去重 | continuation_branch_test、deferred_input_resume_test、continuation_replay_test | 通过，保留重放 |
| 卡牌目标输入只执行一次 | target_frame_test、legacy_target_test | 支付、消费、检查点恢复通过 |
| 延迟与回合结算顺序 | deferred_*、buff_round_order_test、current_rules_lifecycle_test | 通过 |
| 准备技能与新回合暂停 | action_preparing、deferred_input_resume_test、现有生命周期回归 | 通过 |
| 公开来源与剩余伤害差异 | continuation_public_test 的受控等棋盘状态对 | 来源行是唯一观测差异，恢复后实际伤害不同 |
| 私有条件与身份遮罩 | target_frame_test、continuation_public_test、Python 预检 | 对手手牌身份、RNG 不因来源行泄露，敌骰遮罩通过 |
| counter SID/双方视角 | counter_perspective_test、test_perspective_alignment | 沿用 v8 语义，回归通过 |
| buff 引用/归属/排序与来源编码 | entity_observation_test、test_buff_learning | 编码可区分；规则槽位置换不改变语义 |
| 随机游戏全状态与回放 | TestRandomEffectSequences | 12 种子，656 输入，95 回合累计，死亡角色统计 6，21 种观测效果 |
| 独立实例参考模型 | TestRandomIndependentLayersAgainstReference | 24 种子通过 |
| 标签错误及截断污染 | test_dmc_terminal_integrity、test_paired | 未终局拒绝；真实引擎轮数上限平局对双方得分正确 |

新的初训配置预检另覆盖 32 场、1610 输入、16 次死亡换人暂停；两种策略均跑，所有对局
在步数安全上限前达到引擎终局。随机覆盖不替代上方机制专项测试。

仍有边界：完整剩余程序、任意 native hook、私有控制流、公开历史信念建模没有整体完备性
证明。超过两名角色的训练配置被初训 gate 拒绝，需要单独做多选暂停决策表达检查。
新卡的正确性必须先验收；零样本/微调能力只能由后续学习实验判断。

本次没有修改卡牌数值或结算规则，没有新增已复现的规则歧义等待用户裁定。
