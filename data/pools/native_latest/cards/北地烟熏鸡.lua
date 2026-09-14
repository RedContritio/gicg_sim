local card = declare_card("北地烟熏鸡", { dices = { match = 0 } }, { target = "own" })
local food = get_counter("饱腹", Scope.PerChar)
local uses = declare_counter("北地烟熏鸡_次数", Scope.PerChar, 0, { min = 0, max = 1 })
on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card or ctx.card_ref ~= card or ctx.target_player < 0 then return end
  if food:get_at(ctx.target_player, ctx.target_char) > 0 then ctx.playable = false end
end)
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  food:set_at(ctx.target_player, ctx.target_char, 1)
  uses:set_at(ctx.target_player, ctx.target_char, 1)
end)
local prepare = on_action_prepare({ order = uses }, function(ctx)
  if ctx.action_kind ~= ActionKind.Skill or uses:get_at(ctx.actor_player, ctx.actor_char) <= 0 then return end
  local character = _char_by_slot[ctx.actor_player][ctx.actor_char]
  if character.normal_attack ~= ctx.skill_index then return end
  cost_mod(ctx, CostSlot.Any, -1)
end)
on_skill_use(function(ctx)
  if was_applied(ctx, prepare) then uses:sub_at(ctx.actor_player, ctx.actor_char, 1) end
end)
on_round_end_decay({ order = uses }, function(ctx)
  uses:set_at(ctx.actor_player, ctx.actor_char, 0)
end)
register_buff(uses, { remove_on_death = true, expires_round_end = true })
