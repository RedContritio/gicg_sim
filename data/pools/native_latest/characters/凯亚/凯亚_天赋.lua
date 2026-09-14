local character = get_char("凯亚")
local owner, slot = character:owner_player(), character:owner_char()
local active = get_counter("冷血之剑_装备", Scope.Self)
local skill = get_skill(character, "霜袭")
local used = declare_counter("冷血之剑_本回合已用", Scope.Self, 0, { min = 0, max = 1 })
on_skill_use(-10, function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot or ctx.skill_index ~= skill then return end
  if active:get() <= 0 or used:get() > 0 then return end
  used:set(1)
  heal(character, 2)
end)
on_round_start(function(ctx) used:set(0) end)
