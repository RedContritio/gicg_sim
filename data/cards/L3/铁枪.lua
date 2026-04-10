local ref = declare_card("铁枪", 2, { target = "own" })
local equipped = get_counter("equipped", Scope.PerChar)
local last_skill = declare_counter("铁枪_last_skill", Scope.PerChar, -1, { min = -1, max = 9999 })

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

on_skill_use(function(ctx)
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  last_skill:set_at(ctx.actor_player, ctx.actor_char, ctx.skill_index)
end)

on_damage_boost(function(ctx)
  if ctx.source ~= Source.Skill then return end
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  local ls = last_skill:get_at(ctx.actor_player, ctx.actor_char)
  if ls >= 0 and ls == ctx.skill_index then
    ctx.value = ctx.value + 1
    last_skill:set_at(ctx.actor_player, ctx.actor_char, -1)
  end
end)

on_round_start(function(ctx)
  last_skill:fill_all(context_player(), -1)
end)
