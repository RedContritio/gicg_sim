# Contracts

- 佛跳墙 SHALL 仅在 Source.Skill 的增伤阶段增加 2 并消费；回合末
  decay 阶段 SHALL 清除该方所有角色未用的 buff，包括后台。
- 蝶印 SHALL 于 round_end 对所有存活且带印的敌方角色分别造成 1 火，
  随后清印；无印角色不得收到零伤害/附着事件。死亡选择后继续剩余目标，
  不可重新枚举成当前出战角色或重复结算。
- 通用 deal_damage 增加可选 target_counter 过滤：数值 PerChar counter，
  >0 的候选才参与本次伤害。首击前固定筛选结果；沿用完整伤害和输入
  恢复流程，保留 actor 归属；计数器消费仍由 DSL 显式写出。
- 引擎不硬编码蝶印、佛跳墙或任何卡名。target_counter 在 tokenizer 中
  使用稳定关键字 token 265，并在 IR 保留计数器绑定。
- 本次未裁定技能主伤害致死后的挂印/追加目标，也未改变以逸待劳归因。
