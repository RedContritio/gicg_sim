local character = get_char("芭芭拉")
local owner = character:owner_player()
local active = get_counter("光辉的季节_装备", Scope.Self)
local uses = get_counter("歌声之环", Scope.PerPlayer)
local used = declare_counter("光辉的季节_本回合已用", Scope.Self, 0, { min = 0, max = 1 })
local prepare = on_action_prepare({ order = active }, function(ctx)
  if ctx.actor_player ~= owner or ctx.action_kind ~= ActionKind.Switch then return end
  if active:get() <= 0 or used:get() > 0 or uses:get() <= 0 then return end
  if not character:alive() or cost_total(ctx) <= 0 then return end
  cost_reduce(ctx, 1)
end)
on_switch(function(ctx)
  if ctx.actor_player ~= owner or ctx.action_context ~= Action.Switch then return end
  if was_applied(ctx, prepare) then used:set(1) end
end)
on_round_start(function(ctx) used:set(0) end)
