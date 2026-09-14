local card = declare_card("莲花酥", { dices = { match = 1 } }, { target = "own" })
local food = get_counter("饱腹", Scope.PerChar)
local active = declare_counter("莲花酥_状态", Scope.PerChar, 0, { min = 0, max = 1 })
on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card or ctx.card_ref ~= card or ctx.target_player < 0 then return end
  if food:get_at(ctx.target_player, ctx.target_char) > 0 then ctx.playable = false end
end)
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  food:set_at(ctx.target_player, ctx.target_char, 1)
  active:set_at(ctx.target_player, ctx.target_char, 1)
end)
on_damage_reduce_buff({ order = active, order_on = "target" }, function(ctx)
  if active:get_at(ctx.target_player, ctx.target_char) <= 0 or ctx.value <= 0 then return end
  active:set_at(ctx.target_player, ctx.target_char, 0)
  ctx.value = max(0, ctx.value - 3)
end)
on_round_end_decay({ order = active }, function(ctx)
  active:set_at(ctx.actor_player, ctx.actor_char, 0)
end)
register_buff(active, { remove_on_death = true, expires_round_end = true })
