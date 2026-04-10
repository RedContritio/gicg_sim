local 饱腹 = declare_counter("饱腹", Scope.PerChar, 0, { min = 0, max = 1 })

on_round_end_decay(function(ctx)
  饱腹:decay_all(context_player())
end)
