local ref = declare_card("以牙还牙", { dices = { any = 2 } })
local rounds = declare_counter("以牙还牙_rounds", Scope.PerPlayer, 0, { min = 0, max = 2, tag = Tag.Summon })
local tracked_elem = declare_counter("以牙还牙_elem", Scope.PerPlayer, 0, { min = 0, max = 255 })

on_switch(function(ctx)
  local p = ctx.actor_player
  local c = _char_by_slot[p][get_active_char(p)]
  if c then tracked_elem:set_at(p, c.element) end
end)

on_round_start(function(ctx)
  local p = context_player()
  local c = _char_by_slot[p][get_active_char(p)]
  if c then tracked_elem:set_at(p, c.element) end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  rounds:set(2)
end)

on_round_end_post_summon({ order = rounds }, function(ctx)
  if rounds:get() <= 0 then return end
  deal_damage(Target.EnemyActive, tracked_elem:get_at(Player.Enemy), 1, { source = Source.Summon })
end)

on_round_end_decay({ order = rounds }, function(ctx)
  if rounds:get() > 0 then
    rounds:sub(1)
  end
end)

register_buff(rounds, { duration = rounds })
