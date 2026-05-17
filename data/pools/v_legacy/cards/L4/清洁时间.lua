local ref = declare_card("清洁时间", { dices = { any = 3 } })

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  get_counter_group(Tag.Summon):set_at({player = Player.All}, 0)
end)
