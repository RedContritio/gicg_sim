local ref = declare_card("以逸待劳", { dices = { any = 8 } }, { battle_action = true })
local active = declare_counter("以逸待劳_active", Scope.PerPlayer, 0, { min = 0, max = 1, tag = Tag.Support })

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

-- ADR-0019 §B.5 改写: priority bracket idiom 失效后,改 on_after_damage
-- 直接读 ctx.absorbed (engine 在 reduce 阶段后 set 的吸收量)。
on_after_damage(function(ctx)
  if active:get_at(ctx.target_player) <= 0 then return end
  if ctx.absorbed <= 0 then return end
  local p = ctx.target_player
  local own_active = get_active_char(p)
  local elem = _char_by_slot[p][own_active].element
  defer_fn(function()
    deal_damage(Target.EnemyActive, elem, ctx.absorbed, { source = Source.Support })
  end)
end)
