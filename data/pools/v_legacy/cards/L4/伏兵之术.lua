local ref = declare_card("伏兵之术", { dices = { any = 2 } })
local active = declare_counter("伏兵之术_active", Scope.PerPlayer, 0, { min = 0, max = 1 })
local used = declare_counter("伏兵之术_used", Scope.PerPlayer, 0, { min = 0, max = 1 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

-- 同类别减费按 buff 产生顺序结算；费用归零后不消费本效果。
local prepare_id = on_action_prepare({ order = active }, function(ctx)
  if ctx.action_kind ~= ActionKind.Switch then return end
  if active:get_at(ctx.actor_player) <= 0 then return end
  if used:get_at(ctx.actor_player) > 0 then return end
  if cost_total(ctx) == 0 then return end
  cost_mod(ctx, CostSlot.Any, -1)
end)

on_switch({ order = active }, function(ctx)
  if ctx.action_context ~= Action.Switch then return end
  if not was_applied(ctx, prepare_id) then return end
  used:set_at(ctx.actor_player, 1)
end)

on_round_start({ order = active }, function(ctx)
  used:set(0)
end)

register_buff(active, { progress = used })
