-- 官方资料5361：大型风灵，三次结束阶段伤害，离场前仅转换一次。
local character = get_char("砂糖")
local owner = character:owner_player()
local slot = character:owner_char()
local burst = declare_skill(character, "禁·风灵作成·柒伍同构贰型", { dices = { anemo = 3 }, energy = 2 })
local uses = declare_counter("大型风灵", Scope.PerPlayer, 0, { min = 0, max = 3, tag = Tag.Summon })
local element = declare_counter("大型风灵_元素", Scope.PerPlayer, 0, { min = 0, max = 7 })
local talent = get_counter("混元熵增论_装备", Scope.Self)
local enhanced = declare_counter("大型风灵_天赋", Scope.PerPlayer, 0, { min = 0, max = 1 })
local swirl = declare_reaction("Swirl")

on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot or ctx.skill_index ~= burst then return end
  deal_damage(Target.EnemyActive, Element.Anemo, 1)
  if uses:get() <= 0 or enhanced:get() ~= talent:get() then element:set(Element.Anemo) end
  enhanced:set(talent:get())
  uses:set(3)
end)

on_after_reaction({ order = uses }, function(ctx)
  if ctx.actor_player ~= owner or uses:get() <= 0 then return end
  if ctx.source ~= Source.Skill and ctx.source ~= Source.Summon then return end
  if ctx.reaction_kind ~= swirl or element:get() ~= Element.Anemo then return end
  element:set(ctx.reaction_element)
end)

on_round_end_post_summon({ order = uses }, function(ctx)
  if uses:get() <= 0 then return end
  deal_damage(Target.EnemyActive, element:get(), 2, { source = Source.Summon })
  uses:sub(1)
  if uses:get() <= 0 then element:set(Element.None) end
end)
register_buff(uses)

on_damage_add({ order = uses }, function(ctx)
  if ctx.actor_player ~= owner or uses:get() <= 0 or enhanced:get() <= 0 then return end
  if element:get() == Element.Anemo or element:get() == Element.None then return end
  if ctx.element == element:get() then ctx.value = ctx.value + 1 end
end)
