local ref = declare_card("反制", 2, { target = "enemy" })
local debuff = declare_counter("反制_debuff", Scope.PerChar, 0, { min = 0, max = 1 })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  debuff:set_at(ctx.target_player, ctx.target_char, 1)
end)

on_action_prepare(function(ctx)
  if ctx.action_kind ~= ActionKind.Skill then return end
  if debuff:get_at(ctx.actor_player, ctx.actor_char) <= 0 then return end
  ctx.ap_cost = ctx.ap_cost + 1
end)

on_round_end_decay(function(ctx)
  debuff:decay_all(context_player())
end)
