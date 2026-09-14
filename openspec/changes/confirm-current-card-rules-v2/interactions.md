# 交互覆盖矩阵

规则版本：`current-cards-2026-09-11-v2`。手工预期依据见 [规则清单](rules.md)。
本表的“已覆盖”是列明的场景通过，不是穷举组合证明。
所有 Go 测试位于 `gicg_engine/tests/`；下列新用例全部同时检查 P0/P1。

## 本批新增交互与预期

| ID | 组合 / 手工预期 | 测试函数（统一前缀 TestCurrentRules_） | 验证路径 |
| --- | --- | --- | --- |
| I01 | 枪 1 火+2 无，反制 +1 无，乘胜第四次 -3，剩 1 无；只持 1 水也可支付；查询不消费反制 | CostPenaltyRestrictedFirst | 真出牌/技能 |
| I02 | 乘胜将守正 3 水减为 0，仍须 2 能量；1 能量不可用，2 能量恰付一次，追加 2 水、计数只从 3 到 4 | FreeTalentStillPaysEnergyOnce | 真天赋调用技能 |
| I03 | 蝶火枪+佛跳墙+增幅+蒸发：(2+2+2)×2+2=14；敌 HP 15→1，食物/增幅/水附着消费 | AddMultiplyThenReaction | 真出牌/技能，附着夹具 |
| I04 | 荷花酥先把 3 伤归零，不动 2 点猫爪盾；下一击 2 由盾吸收；再 1 伤扣 HP | LotusBeforeShield | 真食物/护盾技能，精确伤害夹具 |
| I05 | 荷花酥完全吸收 3，触发以逸反击 3；下一击无荷花酥，己方扣 3、不再反击 | LotusRetaliatesOnce | 真出牌，精确伤害夹具；仅 HP 结果，Q04 归因未通过 |
| I06 | 碎片击杀对方出战，选择仅含存活替补；强制切换不扣骰、不消费伏兵/瞬身，不推进乘胜；快速牌恢复后行动权仍在出牌方 | ForcedSwitchPreservesCharges | 真卡致死、等待输入、独立克隆恢复 |
| I07 | 先结束方召唤物击杀，暂停换人；选择后另一方召唤物只结算一次，两方寿命各 2→1；源局保持暂停 | RoundEndDeathResumesRemainingSummon | 真双召唤与 EndTurn、克隆恢复 |
| I08 | 双方最后角色各 1 HP、各有以牙还牙；先结束方先击杀并获胜，另一召唤不继续；交换席位结果相同 | FirstEndWinsLethalSummonRace | 真出牌、终局与合法动作 |
| I09 | 以牙还牙连续三个回合：敌 HP 14、13、13，寿命 1、0、0 | SummonExpiresAfterTwoTicks | 真出牌与回合推进 |
| I10 | 三种当前食物分别使目标饱腹，不能再对同一角色使用，后台仍可选；下回合目标重新可选 | FoodSatiationIsPerTargetAndExpires | 真出牌与联合目标枚举 |
| I11 | 伏兵+瞬身让首次切换免费且快速，乘胜仍停在 3；第二次切换用乘胜减免但交行动权；第三次付 1 | FreeFastSwitchAndNextPaidSwitch | 真三牌与连续切换 |
| I12 | 清洁移除以牙还牙，保留蝶火/蝶印/乘胜；回合末仅蝶印造成 1 火并清印 | CleaningPreservesNonSummonStates | 真天赋、技能、清洁和回合末 |

I03 不靠引擎数值生成答案：若错误地先乘后加或将反应一起乘，结果会
不同。I01 故意只提供水骰，防止仅断言总花费而漏掉受限槽减免错误。
I07/I08 分别区分“暂停后继续”和“已终局不得继续”。

## 逐牌覆盖与剩余边界

“基础”均包含上一批 DeclarationLedger 费用/战斗属性。
旧测试简称 CurrentCards_X 表示 TestCurrentCards_X。

| 牌 | 基础/单牌证据 | 交互证据 | 尚未完成的专项或语义边界 |
| --- | --- | --- | --- |
| 碌碌无为 | ImmediateEffectsBothSeats | I01/I02/I06/I11 付费计数 | 无额外机制；仍需未来随机序列检查 |
| 美味烧鸡 | ImmediateEffectsBothSeats；SelectedTargetSurvivesDeferredCloneRestore | I10；YiYiOverhealCounts 为底层治疗夹具 | 致死反击链中的治疗归因 Q04 |
| 佛跳墙 | FoodAndAmplification | I03/I10 | 已由 I13/I14 补非技能过滤与回合末过期；自伤仍按伤害来源分类 |
| 占星 | ImmediateEffectsBothSeats；EnergyAtCapDoesNotTriggerTransfer | FavoniusBothSeats | 双装备多角色传递环未做真卡组合专项 |
| 诅咒 | ImmediateEffectsBothSeats | 守正能量不足已有合法性案例，但未组合诅咒 | 被选后台/0 能量边界专项尚缺 |
| 荷花酥 | LotusThresholdAndConsumption | I04/I05/I10 | 水云同阶段顺序 Q05；穿透有通用管线测试，未做本牌组合 |
| 反制 | ImmediateEffectsBothSeats；TestDiscount_反制_Alone | I01 | 初始零骰费技能的加费门槛 Q01 |
| 以牙还牙 | TestRoundEnd_以牙还牙_* | I07/I08/I09/I12；CleaningRemovesBothSummons | 多召唤同阶段顺序的全面枚举未做 |
| 伏兵之术 | SwitchCardsBothSeats | I06/I11；TestDiscount_伏兵之术_FreeSwitchDoesNotCount | 其他主动切换加费源不在当前牌组 |
| 瞬身之术 | SwitchCardsBothSeats | I06/I11 | 多种快速来源优先级未穷举 |
| 清洁时间 | CleaningRemovesBothSummons | I12 | 扩展池召唤物非寿命辅助计数的清除范围未认证 |
| 玄冰 | XuanBingReplacesOneReaction | 一次反应替换已测 | 替换反应导致多人死亡/连续换人未做专项 |
| 西风剑 | FavoniusBothSeats | 后台装备、下一角色技能能量 | 非技能命中给标记 Q02；装备替换专项未补 |
| 西风长枪 | FavoniusBothSeats；EnergyAtCapDoesNotTriggerTransfer | 能量上限不虚构传递 | 双装备环及换装后计数生命周期专项未补 |
| 蝶鳞 | DieLinBurstTriggersOnce；DieLinHealingThreshold | I12；TestRoundEnd_蝶鳞_* | 后台印及其致死恢复由 I15/I16 覆盖；技能致死追加目标 Q03 仍待定 |
| 守正 | ShouZhengPaysEnergyExactlyOnce；ShouZhengProtectsWaterCloud | I02 | Q05；致死后泼墨目标专项未裁定 |
| 以攻代守 | OffenseConvertsShieldOverflow | 标签 Add→保留 1→穿透链 | 当前赤蝶/墨客不生成护盾；重复 Add 与减伤反击嵌套未穷举 |
| 乘胜追击 | ChengShengFourthPaidOperation；DiceCostReduceRestrictedFirst（engine 包） | I01/I02/I06/I11 | 计数起点已确认；多个减费内部顺序 Q01、调和专项尚缺 |
| 测试卡_增幅 | FoodAndAmplification | I03；碎片不消费已有案例 | 多段技能跨死亡选择的消费专项未补 |
| 测试卡_碎片 | ImmediateEffectsBothSeats | I06 | 本身无持续状态 |
| 测试卡_神秘水流 | MysteryWaterAfterSkillAndReset | 已覆盖技能状态→水伤→蒸发 | 致死与反应扩散未做本牌专项 |

## 验收边界

- 本批要求：21 张牌均有规则条目、证据映射及缺口说明；I01–I12 全部
  通过；新测试不使用动态输出作为预期；版本校验与 Go 回归通过。
- 当前未宣称：所有 P/Q 均得到用户确认，所有两两组合或长序列均覆盖，
  或完成第三步随机对局验证。Q04 是已知实现缺陷，不能用 HP 测试掩盖。
- Q01 计数起点、Q02 佛跳墙、Q03 后台印已裁定；下一批处理剩余边界及 Q04，之后
  再做随机对局、失败序列保存与最小化。

## v2 用户裁定后新增验收

以下测试在 current_rules_clarified_test.go，完整前缀 TestCurrentRules_。

| ID | 场景与独立预期 | 测试 |
| --- | --- | --- |
| I13 | 真碎片及状态/召唤/反应/支援来源伤害不增伤、不消费佛跳墙；之后枪伤害 4，下一枪恢复 2 | FoodOnlySkillDamage |
| I14 | 带未用佛跳墙的角色切到后台，回合末仍清除；下回合回来用枪只造成 2 | UnusedFoodExpiresOnBench |
| I15 | 真蝶鳞+枪挂印后敌方换人，后台带印角色受 1 火；无印出战不受伤、不附着火；次回合不再触发 | BenchMarkHitsOnlyMarkedCharacter |
| I16 | 两个角色均挂印；第一枚印致死，暂停换人；克隆恢复后第二枚印只触发一次并清除全部印，原局不变 | MultipleMarksResumeAfterDeath |
| I17 | 非 PerChar 数值计数器不能作为伤害筛选参数，错误不得退化成全体伤害 | DamageSelectorRejectsNonCounter |

I13–I16 均双席位运行，共 8 个子用例；I17 为参数契约单例。
另以 TestDamageTargetCounterPreservedInIR 验证模型可见规则保留筛选计数绑定。
