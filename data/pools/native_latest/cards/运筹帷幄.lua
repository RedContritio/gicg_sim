-- 最新官方快照原生事件牌。
local card = declare_card("运筹帷幄", { dices = { match = 1 } })
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  draw_card(ctx.actor_player, 2)
end)
