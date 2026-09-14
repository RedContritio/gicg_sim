local ref = declare_card("乘胜追击", { dices = { any = 4 } })
local active = declare_counter("乘胜追击_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })
local action_count = declare_counter("乘胜追击_count", Scope.PerPlayer, 0, { min = 0, max = 99 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

-- 用户规则(2026-09-11):每回合第四次需要消耗骰子的操作减少三个任意骰费用。
-- 同类别按 buff 产生顺序结算；已免费操作不计数。优先减少指定元素、同色费用，最后减少无色费用。
-- 零幅 cost_mod 为候选记录资格；查询本身不改变计数。
local prepare_id = on_action_prepare({ order = active }, function(ctx)
  if active:get_at(ctx.actor_player) <= 0 then return end
  if cost_total(ctx) <= 0 then return end
  if action_count:get_at(ctx.actor_player) == 3 then
    cost_reduce(ctx, 3)
  else
    cost_mod(ctx, CostSlot.Any, 0)
  end
end)

-- 每个已执行操作仅结算一次，包括非战斗牌、快速切换，以及被本卡减至免费
-- 的第四次操作。调和、结束回合和强制切换不支付骰子，不进入该计数。
on_before_turn_flip({ order = active }, function(ctx)
  if not was_applied(ctx, prepare_id) then return end
  action_count:add_at(ctx.actor_player, 1)
end)

on_round_start({ order = active }, function(ctx)
  action_count:set(0)
end)

register_buff(active, { progress = action_count })
