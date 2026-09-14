local character = get_char("迪卢克")
local owner, slot = character:owner_player(), character:owner_char()
local active = get_counter("流火焦灼_装备", Scope.Self)
local count = get_counter("逆焰之刃_本回合次数", Scope.Self)
local skill = get_skill(character, "逆焰之刃")
on_action_prepare({ order = active }, function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot then return end
  if ctx.action_kind ~= ActionKind.Skill or ctx.skill_index ~= skill then return end
  if active:get() <= 0 then return end
  if count:get() == 1 or count:get() == 2 then cost_mod(ctx, CostSlot.Fire, -1) end
end)
