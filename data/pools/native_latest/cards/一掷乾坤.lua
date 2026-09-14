local card = declare_card("一掷乾坤", { dices = {} })
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  choose_reroll(ctx.actor_player, 2)
end)
