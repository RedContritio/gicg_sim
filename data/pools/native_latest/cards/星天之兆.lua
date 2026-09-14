-- 最新官方快照原生事件牌。
local card = declare_card("星天之兆", { dices = { any = 2 } })
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  local character = _char_by_slot[ctx.actor_player][get_active_char(ctx.actor_player)]
  gain_energy(character.energy, 1)
end)
