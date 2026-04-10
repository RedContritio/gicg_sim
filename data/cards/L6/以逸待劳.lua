local ref = declare_card("以逸待劳", 8, { battle_action = true })
local active = declare_counter("以逸待劳_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })
local pre_reduce_value = declare_counter("以逸待劳_pre", Scope.PerPlayer, 0, { min = 0, max = 99 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

on_round_start(function(ctx)
  if active:get() <= 0 then return end
  local ap = get_counter("ap", Scope.PerPlayer)
  ap:add(2)
end)

-- 治疗后反击
on_after_heal(function(ctx)
  if active:get_at(ctx.target_player) <= 0 then return end
  if ctx.value <= 0 then return end
  local p = ctx.target_player
  local own_active = get_active_char(p)
  local elem = _char_by_slot[p][own_active].element
  defer_fn(function()
    deal_damage(Target.EnemyActive, elem, ctx.value, { source = Source.Support })
  end)
end)

-- 减伤阶段：记录护盾前伤害值 → 计算吸收量 → 反击
on_damage_reduce(100, function(ctx)
  if active:get_at(ctx.target_player) <= 0 then return end
  pre_reduce_value:set_at(ctx.target_player, ctx.value)
end)

on_damage_reduce(-100, function(ctx)
  if active:get_at(ctx.target_player) <= 0 then return end
  local before = pre_reduce_value:get_at(ctx.target_player)
  local absorbed = before - ctx.value
  pre_reduce_value:set_at(ctx.target_player, 0)
  if absorbed <= 0 then return end
  local p = ctx.target_player
  local own_active = get_active_char(p)
  local elem = _char_by_slot[p][own_active].element
  defer_fn(function()
    deal_damage(Target.EnemyActive, elem, absorbed, { source = Source.Support })
  end)
end)
