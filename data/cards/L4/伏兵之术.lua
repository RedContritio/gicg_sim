local ref = declare_card("伏兵之术", 2)
local active = declare_counter("伏兵之术_active", Scope.PerPlayer, 0, { min = 0, max = 1 })
local used = declare_counter("伏兵之术_used", Scope.PerPlayer, 0, { min = 0, max = 1 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

on_action_prepare(function(ctx)
  if ctx.action_kind ~= ActionKind.Switch then return end
  if active:get_at(ctx.actor_player) <= 0 then return end
  if used:get_at(ctx.actor_player) > 0 then return end
  ctx.ap_cost = 0
end)

on_switch(function(ctx)
  if ctx.action_context ~= Action.Switch then return end
  if active:get_at(ctx.actor_player) <= 0 then return end
  if used:get_at(ctx.actor_player) > 0 then return end
  used:set_at(ctx.actor_player, 1)
end)

on_round_start(function(ctx)
  used:set(0)
end)
