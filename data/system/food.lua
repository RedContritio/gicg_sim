local 饱腹 = declare_counter("饱腹", Scope.PerChar, 0, { min = 0, max = 1 })

on_round_end_decay({ order = 饱腹 }, function(ctx)
  饱腹:sub_at(ctx.actor_player, ctx.actor_char, 1)
end)

register_buff(饱腹, { expires_round_end = true })
