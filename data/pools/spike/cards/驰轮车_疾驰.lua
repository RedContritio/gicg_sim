-- 驰轮车·疾驰 spike — 验证 declare_card slot=Slot.Specialty + 槽位约束
-- 完整 raw 见 data/cleaned/action/505460_驰轮车_疾驰.yaml
-- 真实卡机制:由玛薇卡技能产生在手牌,装备到玛薇卡的特技槽。
-- spike 验证:打出此牌后玛薇卡 SpecialtyCardRef 被设置;再打第二张
-- 同名(从战技产)被 on_action_check 拒绝。
local ref = declare_card("驰轮车_疾驰", { dices = { same = 1 } }, {
    requires_char = "玛薇卡",
    slot = Slot.Specialty,
})

-- spike 不实现"使用特技"action 候选,只验证装备装上即可。
-- 真实卡的特技效果(行动阶段开始时生成 2 万能骰 + 消耗 1 夜魂值)
-- 留 future,见 ADR-0012 specialty action 子项。
on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  -- 装备时给玩家加 2 个万能骰(模拟"使用特技"的核心效果之一,
  -- 验证 add_dice builtin 能 work)
  add_dice(ctx.actor_player, DiceColor.Omni, 2)
end)
