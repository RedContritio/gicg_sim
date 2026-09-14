local ref = declare_card("速速茶点", { dices = { any = 1 } }, { target = "own" })
local 饱腹 = get_counter("饱腹", Scope.PerChar)
local buff = declare_counter("速速茶点_buff", Scope.PerChar, 0, { min = 0, max = 2 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if ctx.target_player < 0 then return end
  if 饱腹:get_at(ctx.target_player, ctx.target_char) > 0 then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  饱腹:set_at(ctx.target_player, ctx.target_char, 1)
  buff:set_at(ctx.target_player, ctx.target_char, 2)
end)

local prepare_id = on_action_prepare({ order = buff }, function(ctx)
  if ctx.action_kind ~= ActionKind.Skill then return end
  if buff:get_at(ctx.actor_player, ctx.actor_char) <= 0 then return end
  local c = _char_by_slot[ctx.actor_player][ctx.actor_char]
  if not c or c.normal_attack ~= ctx.skill_index then return end
  if cost_total(ctx) == 0 then return end
  cost_mod(ctx, CostSlot.Any, -1)
end)

on_skill_use({ order = buff }, function(ctx)
  if not was_applied(ctx, prepare_id) then return end
  buff:sub_at(ctx.actor_player, ctx.actor_char, 1)
end)

on_round_end_decay({ order = buff }, function(ctx)
  buff:set_at(ctx.actor_player, ctx.actor_char, 0)
end)

register_buff(buff, { remove_on_death = true, expires_round_end = true })
