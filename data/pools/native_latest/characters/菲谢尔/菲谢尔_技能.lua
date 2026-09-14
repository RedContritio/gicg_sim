-- 最新官方资料5365；仅普通七圣召唤规则，不混入自行巧局变体。
local character = get_char("菲谢尔")
local owner, slot = character:owner_player(), character:owner_char()
local normal = declare_skill(character, "罪灭之矢", { dices = { electro = 1, any = 2 } })
local skill = declare_skill(character, "夜巡影翼", { dices = { electro = 3 } })
local burst = declare_skill(character, "至夜幻现", { dices = { electro = 3 }, energy = 3 })
local uses = declare_counter("奥兹", Scope.PerPlayer, 0, { min = 0, max = 2, tag = Tag.Summon })
local talent = get_counter("噬星魔鸦_装备", Scope.Self)
local enhanced = declare_counter("奥兹_天赋", Scope.PerPlayer, 0, { min = 0, max = 1 })
on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot or ctx.skill_index ~= normal then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
  if uses:get() > 0 and enhanced:get() > 0 then
    deal_damage(Target.EnemyActive, Element.Electro, 2, { source = Source.Summon })
    uses:sub(1)
  end
end)
on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot or ctx.skill_index ~= skill then return end
  deal_damage(Target.EnemyActive, Element.Electro, 1)
  enhanced:set(talent:get())
  uses:set(2)
end)
on_skill_use(function(ctx)
  if ctx.actor_player ~= owner or ctx.actor_char ~= slot or ctx.skill_index ~= burst then return end
  local victim = _char_by_slot[1 - owner][get_active_char(1 - owner)]
  deal_damage(victim, Element.Electro, 4)
  deal_damage(victim, Element.Piercing, 2, { source = Source.Skill, other_characters = true })
end)
on_round_end_post_summon({ order = uses }, function(ctx)
  if uses:get() <= 0 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 1, { source = Source.Summon })
  uses:sub(1)
end)
register_buff(uses)
