local ref = declare_card("铁弓", { dices = { any = 2 } }, { target = "own", requires_weapon = Weapon.Bow })
local equipped = get_counter("equipped", Scope.PerChar)
local used = declare_counter("铁弓_used", Scope.PerPlayer, 0, { min = 0, max = 1 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if ctx.target_player < 0 then return end
  local c = _char_by_slot[ctx.target_player][ctx.target_char]
  if not c or c.weapon ~= Weapon.Bow then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  equipped:set_at(ctx.target_player, ctx.target_char, ref)
end)

on_action_prepare({ order = equipped }, function(ctx)
  if ctx.action_kind ~= ActionKind.Switch then return end
  local p = ctx.actor_player
  local active = get_active_char(p)
  if equipped:get_at(p, active) ~= ref then return end
  if used:get_at(p) > 0 then return end
  ctx.battle_action = false
end)

on_switch({ order = equipped }, function(ctx)
  if ctx.action_context ~= Action.Switch then return end
  local p = ctx.actor_player
  local prev_active = ctx.actor_char
  if equipped:get_at(p, prev_active) ~= ref then return end
  if used:get_at(p) > 0 then return end
  used:set_at(p, 1)
end)

on_round_start(function(ctx)
  used:set(0)
end)
