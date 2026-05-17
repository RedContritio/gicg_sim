local frozen = get_counter("冻结", Scope.PerChar)

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Skill then return end
  if frozen:get_at(ctx.actor_player, ctx.actor_char) > 0 then
    ctx.playable = false
  end
end)

on_round_end_decay(function(ctx)
  frozen:decay_all(context_player())
end)
