local card = declare_card("派蒙", { dices = { match = 3 } }, { slot = Slot.Support })
local uses = declare_counter("派蒙_次数", Scope.PerPlayer, 0, { min = 0, max = 2 })
register_buff(uses, { independent = true })
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  spawn_support_buff(uses, 2, -1)
end)
on_round_start({ order = uses }, function(ctx)
  local p = context_player()
  add_dice(p, DiceColor.Omni, 2)
  uses:sub_at(p, 1)
  if uses:get_at(p) <= 0 then remove_support(p, card) end
end)
