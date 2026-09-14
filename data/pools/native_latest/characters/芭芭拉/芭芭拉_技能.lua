-- 最新官方资料5372；水环的水附着与治疗独立，禁止用零伤害代替附着。
local character = get_char("芭芭拉")
local owner, slot = character:owner_player(), character:owner_char()
local normal = declare_skill(character, "水之浅唱", { dices = { water = 1, any = 2 } })
local skill = declare_skill(character, "演唱，开始♪", { dices = { water = 3 } })
local burst = declare_skill(character, "闪耀奇迹", { dices = { water = 3 }, energy = 3 })
local uses = declare_counter("歌声之环", Scope.PerPlayer, 0, { min = 0, max = 2, tag = Tag.Summon })
on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot then return end
  if ctx.skill_index == normal then
    deal_damage(Target.EnemyActive, Element.Water, 1)
  elseif ctx.skill_index == skill then
    deal_damage(Target.EnemyActive, Element.Water, 1)
    uses:set(2)
  elseif ctx.skill_index == burst then
    heal(Target.OwnAll, 4)
  end
end)
on_round_end_post_summon({ order = uses }, function(ctx)
  if uses:get() <= 0 then return end
  heal(Target.OwnAll, 1)
  apply_element(Target.OwnActive, Element.Water)
  uses:sub(1)
end)
register_buff(uses)
