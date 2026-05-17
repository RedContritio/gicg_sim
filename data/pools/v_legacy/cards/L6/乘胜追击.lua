local ref = declare_card("乘胜追击", { dices = { any = 4 } })
local active = declare_counter("乘胜追击_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })
local action_count = declare_counter("乘胜追击_count", Scope.PerPlayer, 0, { min = 0, max = 99 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

-- Count actually executed battle actions. on_before_turn_flip fires
-- once per real action execution (not per candidate enumeration), so
-- this reliably advances the counter one per turn.
-- 语义差异说明:免费行动(例如被伏兵之术免费的切换)也会计入这个 count。
-- 原版 GI TCG 里免费行动不计入,这里接受这个 minor drift —— 精确区分
-- 需要把"是否真有支付骰子"传到 before_turn_flip 这一帧,新 ctx 字段。
on_before_turn_flip(function(ctx)
  if active:get_at(ctx.actor_player) <= 0 then return end
  if not ctx.battle_action then return end
  action_count:add_at(ctx.actor_player, 1)
end)

-- 第 4 次 battle action 免费。优先级 2000 让这个 hook 在所有 discount
-- (包括 priority=1000 的 伏兵之术)之前 fire,所以 乘胜追击 清零之后
-- 其他折扣会被 gate 短路掉,不会浪费 charge。
on_action_prepare(2000, function(ctx)
  if active:get_at(ctx.actor_player) <= 0 then return end
  if action_count:get_at(ctx.actor_player) ~= 3 then return end
  if cost_total(ctx) == 0 then return end
  cost_mod(ctx, CostSlot.All, -99)
end)

on_round_start(function(ctx)
  action_count:set(0)
end)
