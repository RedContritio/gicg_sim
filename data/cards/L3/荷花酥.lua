local ref = declare_card("荷花酥", 2, { target = "own" })
local 饱腹 = get_counter("饱腹", Scope.PerChar)
local buff = declare_counter("荷花酥_buff", Scope.PerChar, 0, { min = 0, max = 1 })

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
  buff:set_at(ctx.target_player, ctx.target_char, 1)
end)

on_damage_reduce(function(ctx)
  if buff:get_at(ctx.target_player, ctx.target_char) <= 0 then return end
  if ctx.value > 2 then
    ctx.value = 0
    buff:set_at(ctx.target_player, ctx.target_char, 0)
  end
end)

on_round_end_decay(function(ctx)
  buff:decay_all(context_player())
end)
