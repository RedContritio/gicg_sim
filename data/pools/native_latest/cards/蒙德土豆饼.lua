-- cards/事件/蒙德土豆饼.lua
-- source: data/cleaned/action/5529_蒙德土豆饼.yaml
-- 字段对照 (强制锁定):
--   id=5529 sub_class=事件牌 cost={同色:1}
--   effect: 治疗目标角色 2 点
-- 饱腹 status 由 data/system/food.lua 统一处理

local ref = declare_card("蒙德土豆饼", { dices = { match = 1 } }, { target = "own" })
local 饱腹 = get_counter("饱腹", Scope.PerChar)

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if ctx.target_player < 0 then return end
  if 饱腹:get_at(ctx.target_player, ctx.target_char) > 0 then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  饱腹:set_at(ctx.target_player, ctx.target_char, 1)
  heal(Target.CardTarget, 2)
end)
