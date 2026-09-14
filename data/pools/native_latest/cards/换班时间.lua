local card = declare_card("换班时间", { dices = {} })
local active = declare_counter("换班时间_待生效", Scope.PerPlayer, 0, { min = 0, max = 1 })
on_card_play(function(ctx)
  if ctx.card_ref == card then active:set_at(ctx.actor_player, 1) end
end)
local prepare = on_action_prepare({ order = active }, function(ctx)
  if ctx.action_kind ~= ActionKind.Switch or active:get_at(ctx.actor_player) <= 0 then return end
  cost_reduce(ctx, 1)
end)
on_switch(function(ctx)
  if ctx.action_context ~= Action.Switch then return end
  if was_applied(ctx, prepare) then active:set_at(ctx.actor_player, 0) end
end)
register_buff(active)
