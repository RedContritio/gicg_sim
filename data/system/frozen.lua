local frozen = get_counter("冻结", Scope.PerChar)

on_action_check({ order = frozen }, function(ctx)
  if ctx.action_kind ~= ActionKind.Skill then return end
  if frozen:get_at(ctx.actor_player, ctx.actor_char) > 0 then
    ctx.playable = false
  end
end)

on_round_end_decay({ order = frozen }, function(ctx)
  frozen:sub_at(ctx.actor_player, ctx.actor_char, 1)
end)

register_buff(frozen, { expires_round_end = true })
