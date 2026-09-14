local ref = declare_card("西风剑", { dices = { any = 3 } }, { target = "own", requires_weapon = Weapon.Sword })
local equipped = get_counter("equipped", Scope.PerChar)
local next_bonus = declare_counter("西风剑_next_bonus", Scope.PerChar, 0, { min = 0, max = 1 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if ctx.target_player < 0 then return end
  local c = _char_by_slot[ctx.target_player][ctx.target_char]
  if not c or c.weapon ~= Weapon.Sword then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  equipped:set_at(ctx.target_player, ctx.target_char, ref)
end)

on_damage_add({ order = equipped }, function(ctx)
  if ctx.source ~= Source.Skill then return end
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  ctx.value = ctx.value + 1
end)

on_after_damage({ order = equipped }, function(ctx)
  if ctx.source ~= Source.Skill then return end
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  if not ctx.hit then return end
  local next_c = get_next_char(ctx.actor_player, ctx.actor_char)
  if next_c ~= ctx.actor_char then
    next_bonus:set_at(ctx.actor_player, next_c, 1)
  end
end)

on_skill_use({ order = next_bonus }, function(ctx)
  if next_bonus:get_at(ctx.actor_player, ctx.actor_char) <= 0 then return end
  local c = _char_by_slot[ctx.actor_player][ctx.actor_char]
  if c then gain_energy(c.energy, 1) end
  next_bonus:set_at(ctx.actor_player, ctx.actor_char, 0)
end)

on_round_end_decay({ order = next_bonus }, function(ctx)
  next_bonus:set_at(ctx.actor_player, ctx.actor_char, 0)
end)

register_buff(next_bonus, { remove_on_death = true, expires_round_end = true })
