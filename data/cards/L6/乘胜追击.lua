local ref = declare_card("乘胜追击", 4)
local active = declare_counter("乘胜追击_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })
local action_count = declare_counter("乘胜追击_count", Scope.PerPlayer, 0, { min = 0, max = 99 })
local original_ap = declare_counter("乘胜追击_orig_ap", Scope.PerPlayer, 0, { min = 0, max = 99 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

-- 最高优先级：记录原始 AP 消耗
on_action_prepare(100, function(ctx)
  if active:get_at(ctx.actor_player) <= 0 then return end
  original_ap:set_at(ctx.actor_player, ctx.ap_cost)
end)

-- 最低优先级：按原始 AP 判断，第四次免费
on_action_prepare(-100, function(ctx)
  if active:get_at(ctx.actor_player) <= 0 then return end
  if original_ap:get_at(ctx.actor_player) <= 0 then return end
  action_count:add_at(ctx.actor_player, 1)
  if action_count:get_at(ctx.actor_player) == 4 then
    ctx.ap_cost = 0
  end
end)

on_round_start(function(ctx)
  action_count:set(0)
end)
