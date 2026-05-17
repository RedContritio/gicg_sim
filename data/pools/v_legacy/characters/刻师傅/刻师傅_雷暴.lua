local 刻师傅 = get_char("刻师傅")
local my_player = 刻师傅:owner_player()
local my_char = 刻师傅:owner_char()

local 雷暴 = declare_skill(刻师傅, "雷暴", { dices = { electro = 3 }, energy = 3 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 雷暴 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 3)
  deal_damage(Target.EnemyNonActive, Element.Piercing, 2)
end)
