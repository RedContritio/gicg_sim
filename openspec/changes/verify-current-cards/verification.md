# 当前用牌核验（2026-09-11）

## 范围与结论

非归档配置引用 `v_legacy` 与 `test_basic`，角色为赤蝶、墨客。Stage 3
production 声明 26 张牌，双方各 15 张实际牌组的并集为 17 张。其余当前
默认/冒烟配置加入 3 张测试牌；DMC 填充牌为碌碌无为，共 21 张。

本次是项目自定义规则的实现核验，**不是官方七圣召唤规则认证**。
没有拿引擎输出生成正确答案；费用采用显式清单，效果采用注释、已有
规则案例和手工预期数值。由于缺少独立完整规则说明，不能把有限用例通过
称为所有卡牌交互均已认证。两项规则已由用户于 2026-09-11 确认，并补充验收。

## 逐牌证据

所有 21 张牌的基础骰费、能量费和战斗行动标记均由
`TestCurrentCards_DeclarationLedger` 检查。下表记录实际覆盖的行为。

| 牌 | 已覆盖行为 | 主要测试（gicg_engine/tests） |
| --- | --- | --- |
| 碌碌无为 | 支付 1 骰、弃牌、无额外效果、不交出行动权 | current_cards_audit |
| 美味烧鸡 | 治疗 1、饱腹、双席位、后台目标、延迟治疗与克隆恢复 | current_cards_audit / current_cards_targets |
| 佛跳墙 | 饱腹、下一次伤害 +2、仅消耗一次 | current_cards_audit / current_cards_interactions |
| 占星 | 目标能量 +2；满能量时不虚构西风长枪传递 | current_cards_audit / current_cards_targets |
| 诅咒 | 敌方目标能量 -1、双方席位 | current_cards_audit |
| 荷花酥 | 2 点伤害不消费；3 点伤害归零并消费；后续伤害恢复正常 | current_cards_interactions |
| 反制 | 目标标记；下一技能 +1 费用、消费标记 | current_cards_audit / discount_interaction |
| 以牙还牙 | 双席位回合末目标/元素/归属；清洁后停止伤害 | round_end_actor / current_cards_interactions |
| 伏兵之术 | 真出牌后首次切换免骰、第二次收费；与乘胜折扣不浪费次数 | current_cards_interactions / discount_interaction |
| 瞬身之术 | 真出牌后首次切换不交行动权，第二次正常 | current_cards_interactions |
| 清洁时间 | 清除双方以牙还牙，回合末不再触发 | current_cards_interactions |
| 玄冰 | 替换一次超导为冰元素全体伤害；消费效果；不伤己方 | current_cards_targets |
| 西风剑 | 装备后台剑角色、技能 +1 伤害、下个角色技能获得额外能量 | current_cards_interactions |
| 西风长枪 | 技能能量向下一角色传递、第二技能额外能量、上限不虚假触发 | current_cards_interactions / current_cards_targets |
| 蝶鳞 | 激活蝶火、标记、回合末伤害、回火追加伤害仅一次、低血量治疗 | talent_cards / round_end_actor / current_cards_audit / current_cards_talents |
| 守正 | 0/1 能量不可出，2 能量可出且恰好扣除；即时 2 伤害、2 层泼墨；正气获得并替代水云消耗 | current_cards_talents |
| 以攻代守 | 猫爪护盾新增 2 点时保留 1 点，溢出 1 点造成穿透伤害 | current_cards_interactions |
| 乘胜追击 | 每回合第四次付费操作减最多 3 骰，受限费用优先；第五次正常收费 | discount_interaction / current_cards_confirmed_rules |
| 测试卡_增幅 | 2 同色费用、下一技能伤害翻倍、碎片不消费、后续技能恢复 | current_cards_audit / current_cards_interactions |
| 测试卡_碎片 | 1 骰、1 物理伤害、不消费技能增幅 | current_cards_audit / current_cards_interactions |
| 测试卡_神秘水流 | 未用技能时 2 物理伤害；技能后 2 水伤害及蒸发；下回合重置技能标记 | current_cards_audit / current_cards_targets |

角色方面新增验证：赤蝶的枪/蝶火/回火及低血量治疗边界；墨客的墨意
伤害与水云减伤、水龙吟费用与泼墨追加伤害。均对 P0/P1 执行。

1v1 中没有切换/后台角色，也没有猫爪盾；为验证这些牌的机制，部分用例
使用 2v2 或猫咪作为机制夹具。这不改变生产配置。

## 声明池内但当前实际牌组未使用

以逸待劳、速速茶点、铁剑、铁枪、铁弓、刺刺猫爪、发现静电、星愿。
速速茶点此次另补双席位实战费用/消耗测试；铁剑/铁枪与三张天赋已有
部分回归，但这些未入组牌尚不宣称完成全行为认证。以逸待劳已有双席位
治疗/吸收反击测试，另补满血和部分溢出治疗反击；铁弓也需后续补专项实战认证。

## 本次修复

1. `Target.CardTarget` 读取无人更新的 runtime 字段，错误默认 P0C0。
   改从执行帧读取选择，保留嵌套/延迟/克隆语义。
2. 武器牌错误要求出战角色满足武器类型。改检查具体装备目标。
3. 普通技能能量直接写 counter，绕过能量事件。改走事件管线。
   后置能量事件仅报告实际正增量，并增加递归深度保护。
4. 卡牌声明的能量成本未检查、未支付。补卡牌合法性及一次性消费。
5. 蝶鳞额外伤害反复触发自身，5 点预期伤害变成连续伤害直到击杀。
   限制触发源为技能伤害；基础回火治疗同样排除追加状态伤害。
6. 15 点生命上限的半血判断被整数除法截断；改为 `hp*2 < max_hp`。
7. 蝶鳞在基础治疗之后重新判断低血量而漏掉额外治疗。改在治疗前加 1。
8. 标签写回调传入无法解析的汇总代理，导致以攻代守不工作。
   改传入本次被写入 counter 的具体引用。
9. `cancel()` 为空实现，守正的正气无法阻止水云消耗。补当前钩子上下文
   的取消，嵌套恢复和 reset/clone 生命周期管理。

## 已确认规则

- 乘胜追击按付费操作计数，包含快速牌；第四次减免总数最多为 3，
  优先指定元素、同色，然后无色。新增双席位出牌、普攻、战技、同色牌、
  切换用例，检查激活不计数、查询无副作用、第五次收费、回合重置。
- 以逸待劳保留治疗请求量反击。双席位满血和 14/15 血时接受 3 点
  治疗，均反击 3 点，最终己方 15 血、敌方 12 血。
- 底层费用测试覆盖混合受限费用、低于减免额、纯元素/同色/无色费用
  和负数中间槽；DSL tokenizer 与 IR 注册同时更新。

## 验证结果

- 新增专项：19 个顶层测试、105 个子用例通过，无跳过。
  日志 `/private/tmp/gicg-current-card-cases.jsonl`。
- Go 引擎所有包与 MCTS 竞态测试通过：`gicg-confirmed-rules-race.log`。
- 原生 actor 竞态测试通过：`gicg-confirmed-rules-actor.log`。
- 重建 C shared 库后，Python 环境及四个 MCTS 集成模块 **177 通过**：
  `gicg-confirmed-rules-python.log`。
- 前述完整训练回归发生在本次卡牌修复之前，不能用其 1208 通过来宣称
  本次训练全量已重跑。本次按规则/引擎及调用接口范围验证。
- `go build ./...`、OpenSpec 索引与 diff 空白检查通过。

本次改变了部分实际对局结果与合法动作，旧训练结果不能直接视为修复后
规则下的性能证据；规则来源文件哈希和引擎版本应随新评测保存。
