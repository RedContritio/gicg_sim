-- cards/事件/最好的伙伴.lua
-- source: data/cleaned/action/5480_最好的伙伴_.yaml
-- 字段对照 (强制锁定):
--   id=5480 sub_class=事件牌 cost={无色:2}
--   effect: 生成 2 个万能元素
--   declare_card name 「最好的伙伴！」严格对照 cleaned yaml name(含全角 ！)。
--   lua 文件名不带 ！ 仅出于跨平台路径稳定性(macOS/Windows shell quoting);
--   declare_card 内 name 是 deck-lookup key,必须 byte-match cleaned。
-- ref TS (332001): TheBestestTravelCompanion — costVoid(2).generateDice(DiceType.Omni, 2)

local ref = declare_card("最好的伙伴！", { dices = { any = 2 } })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  add_dice(ctx.actor_player, DiceColor.Omni, 2)
end)
