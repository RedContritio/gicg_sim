-- 官方快照 5490：本回合己方角色被击倒后可用，每回合限打出一张。
local card = declare_card("本大爷还没有输！", { dices = {} })
local defeated = declare_counter("本大爷还没有输_本回合被击倒", Scope.PerPlayer, 0, { min = 0, max = 1 })
local used = declare_counter("本大爷还没有输_本回合已用", Scope.PerPlayer, 0, { min = 0, max = 1 })
on_death(function(ctx)
  defeated:set_at(ctx.actor_player, 1)
end)
on_round_start(function(ctx)
  defeated:set_at(0, 0)
  defeated:set_at(1, 0)
  used:set_at(0, 0)
  used:set_at(1, 0)
end)
on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card or ctx.card_ref ~= card then return end
  if defeated:get_at(ctx.actor_player) == 0 or used:get_at(ctx.actor_player) > 0 then
    ctx.playable = false
  end
end)
on_card_play(function(ctx)
  if ctx.card_ref ~= card then return end
  used:set_at(ctx.actor_player, 1)
  add_dice(ctx.actor_player, DiceColor.Omni, 1)
  local character = _char_by_slot[ctx.actor_player][get_active_char(ctx.actor_player)]
  gain_energy(character.energy, 1)
end)
