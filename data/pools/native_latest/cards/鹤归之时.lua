local card = declare_card("鹤归之时", { dices = { match = 1 } })
local active = declare_counter("鹤归之时_待生效", Scope.PerPlayer, 0, { min = 0, max = 1 })
on_card_play(function(ctx)
  if ctx.card_ref == card then active:set_at(ctx.actor_player, 1) end
end)
on_skill_use(-20, function(ctx)
  if active:get_at(ctx.actor_player) <= 0 then return end
  active:set_at(ctx.actor_player, 0)
  force_switch_next(ctx.actor_player)
end)
register_buff(active)
