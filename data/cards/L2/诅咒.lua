local ref = declare_card("诅咒", 2, { target = "enemy" })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  local c = _char_by_slot[ctx.target_player][ctx.target_char]
  consume_energy(c.energy, 1)
end)
