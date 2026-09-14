local card = declare_card("烤蘑菇披萨", { dices = { match = 1 } }, { target = "own" })
local food = get_counter("饱腹", Scope.PerChar)
local active = declare_counter("烤蘑菇披萨_状态", Scope.PerChar, 0, { min = 0, max = 2 })
on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card or ctx.card_ref ~= card or ctx.target_player < 0 then return end
  if food:get_at(ctx.target_player, ctx.target_char) > 0 then ctx.playable = false end
end)
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  food:set_at(ctx.target_player, ctx.target_char, 1)
  active:set_at(ctx.target_player, ctx.target_char, 2)
  heal(Target.CardTarget, 1)
end)
on_round_end({ order = active, order_on = "target" }, function(ctx)
  local character = _char_by_slot[ctx.actor_player][ctx.actor_char]
  if active:get_at(ctx.actor_player, ctx.actor_char) <= 0 then return end
  heal(character, 1)
  active:sub_at(ctx.actor_player, ctx.actor_char, 1)
end)
register_buff(active, { remove_on_death = true })
