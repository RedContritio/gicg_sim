-- 官方资料5375：寒冰之棱是队伍状态，角色死亡不移除。
local character = get_char("凯亚")
local owner = character:owner_player()
local slot = character:owner_char()
local burst = declare_skill(character, "凛冽轮舞", { dices = { ice = 4 }, energy = 2 })
local uses = declare_counter("寒冰之棱", Scope.PerPlayer, 0, { min = 0, max = 3 })
on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot or ctx.skill_index ~= burst then return end
  deal_damage(Target.EnemyActive, Element.Ice, 1)
  uses:set(3)
end)
on_switch({ order = uses }, function(ctx)
  if ctx.actor_player ~= owner or uses:get() <= 0 then return end
  uses:sub(1)
  deal_damage(Target.EnemyActive, Element.Ice, 2, { source = Source.Status })
end)
register_buff(uses)
