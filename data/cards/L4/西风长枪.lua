local ref = declare_card("西风长枪", 3, { target = "own" })
local equipped = get_counter("equipped", Scope.PerChar)
local skill_count = declare_counter("西风长枪_skill_count", Scope.PerPlayer, 0, { min = 0, max = 99 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if ctx.target_player < 0 then return end
  local c = _char_by_slot[ctx.target_player][ctx.target_char]
  if not c or c.weapon ~= Weapon.Polearm then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  equipped:set_at(ctx.target_player, ctx.target_char, ref)
end)

-- 每次装备角色获得能量时，下一个角色也获得 1 点
on_after_energy_gain(function(ctx)
  if equipped:get_at(ctx.target_player, ctx.target_char) ~= ref then return end
  local next_c = get_next_char(ctx.target_player, ctx.target_char)
  if next_c ~= ctx.target_char then
    local nc = _char_by_slot[ctx.target_player][next_c]
    if nc then gain_energy(nc.energy, 1) end
  end
end)

-- 每回合第二次使用技能，额外 +1 能量
on_skill_use(function(ctx)
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  skill_count:add_at(ctx.actor_player, 1)
  if skill_count:get_at(ctx.actor_player) == 2 then
    local c = _char_by_slot[ctx.actor_player][ctx.actor_char]
    if c then gain_energy(c.energy, 1) end
  end
end)

on_round_start(function(ctx)
  skill_count:set(0)
end)
