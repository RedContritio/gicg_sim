local ref = declare_card("碌碌无为", 1)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
end)
