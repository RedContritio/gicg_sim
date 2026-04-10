local ref = declare_card("占星", 2, { target = "own" })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  local c = _char_by_slot[ctx.target_player][ctx.target_char]
  gain_energy(c.energy, 2)
end)
