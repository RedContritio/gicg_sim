-- characters/刻师傅/刻师傅_剑.lua
-- 普攻：消耗 3 AP，造成 2 物理伤害

local 刻师傅 = get_char("刻师傅")
local 剑 = declare_skill(刻师傅, "剑", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 剑 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
