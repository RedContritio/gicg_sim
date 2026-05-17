local ref = declare_card("美味烧鸡", { dices = { any = 1 } }, { target = "own" })
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
  heal(Target.CardTarget, 1)
end)
