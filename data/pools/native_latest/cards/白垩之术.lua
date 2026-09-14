local card = declare_card("白垩之术", { dices = { match = 1 } })
on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card or ctx.card_ref ~= card then return end
  local character = _char_by_slot[ctx.actor_player][get_active_char(ctx.actor_player)]
  local energy = character.energy
  if energy:get() >= energy:cmax() or background_energy(ctx.actor_player) <= 0 then
    ctx.playable = false
  end
end)
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  -- 用户确认：两后台各扣1；出战封顶，不保留溢出的后台充能。
  transfer_energy_from_background(ctx.actor_player, 1, 2)
end)
