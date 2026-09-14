local ref = declare_card("铁剑", { dices = { any = 2 } }, { target = "own", requires_weapon = Weapon.Sword })
local equipped = get_counter("equipped", Scope.PerChar)
local last_skill = declare_counter("铁剑_last_skill", Scope.PerChar, nil, { ref_kind = RefKind.Skill })

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

on_skill_use({ order = equipped }, function(ctx)
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  if last_skill:get_at(ctx.actor_player, ctx.actor_char) == ctx.skill_index then
    -- Same skill as last time → streak consumed, reset marker
    last_skill:set_at(ctx.actor_player, ctx.actor_char, nil)
  else
    -- New skill → remember it for next use
    last_skill:set_at(ctx.actor_player, ctx.actor_char, ctx.skill_index)
  end
end)

on_action_prepare({ order = equipped }, function(ctx)
  if ctx.action_kind ~= ActionKind.Skill then return end
  if equipped:get_at(ctx.actor_player, ctx.actor_char) ~= ref then return end
  if last_skill:get_at(ctx.actor_player, ctx.actor_char) ~= ctx.skill_index then return end
  if cost_total(ctx) == 0 then return end
  cost_mod(ctx, CostSlot.Any, -1)
end)

on_round_start(function(ctx)
  last_skill:fill_all(context_player(), nil)
end)
