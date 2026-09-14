local card = declare_card("送你一程", { dices = { any = 2 } }, { target = "enemy_summon" })
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  selected_buff():sub(2)
end)
