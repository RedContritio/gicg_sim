local AP_RESET = 8
local SWITCH_COST = 1

local ap = declare_counter("ap", Scope.PerPlayer, 0, { max = 12 })
local round_num = declare_counter("round_num", Scope.Global, 0, { min = 0, max = 999 })
local round1_first_player = declare_counter("round1_first_player", Scope.Global, -1, { min = -1, max = 1 })

on_round_start(function(ctx)
  ap:set(AP_RESET)
  if context_player() == 0 then
    round_num:add(1)
    if round_num:get() == 1 then
      round1_first_player:set(get_turn())
    end
  end
end)

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Skill and ctx.action_kind ~= ActionKind.Card then return end
  if ctx.ap_cost > 0 and ap:get() < ctx.ap_cost then
    ctx.playable = false
  end
end)

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Switch then return end
  if ap:get() < SWITCH_COST then
    ctx.playable = false
  end
end)

on_switch(function(ctx)
  if ctx.action_context == Action.Switch then
    ap:sub(SWITCH_COST)
  end
end)
