-- 最新官方资料5369；第三次战技增伤、两回合火附魔。
local character = get_char("迪卢克")
local owner, slot = character:owner_player(), character:owner_char()
local normal = declare_skill(character, "淬炼之剑", { dices = { fire = 1, any = 2 } })
local skill = declare_skill(character, "逆焰之刃", { dices = { fire = 3 } })
local burst = declare_skill(character, "黎明", { dices = { fire = 4 }, energy = 3 })
local count = declare_counter("逆焰之刃_本回合次数", Scope.Self, 0, { min = 0, max = 999 })
local infusion = declare_counter("迪卢克_火元素附魔", Scope.Self, 0, { min = 0, max = 2 })
on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot then return end
  if ctx.skill_index == normal then
    deal_damage(Target.EnemyActive, Element.Physical, 2)
  elseif ctx.skill_index == skill then
    count:add(1)
    local damage = 3
    if count:get() == 3 then damage = 5 end
    deal_damage(Target.EnemyActive, Element.Fire, damage)
  elseif ctx.skill_index == burst then
    deal_damage(Target.EnemyActive, Element.Fire, 8)
    infusion:set(2)
  end
end)
on_round_start(function(ctx) count:set(0) end)
on_damage_type({ order = infusion }, function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot then return end
  if infusion:get() > 0 and ctx.element == Element.Physical then ctx.element = Element.Fire end
end)
on_round_end_decay({ order = infusion }, function(ctx)
  if infusion:get() > 0 then infusion:sub(1) end
end)
register_buff(infusion, { remove_on_death = true })
