local 刻师傅 = get_char("刻师傅")
local 雷暴 = declare_skill(刻师傅, "雷暴", 3, 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 雷暴 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 3)
  deal_damage(Target.EnemyNonActive, Element.None, 2, { penetrate = true })
end)
