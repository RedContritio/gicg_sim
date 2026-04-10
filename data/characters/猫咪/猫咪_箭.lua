-- characters/猫咪/猫咪_箭.lua
-- 普攻：消耗 3 AP，造成 2 物理伤害

local 猫咪 = get_char("猫咪")
local 箭 = declare_skill(猫咪, "箭", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 箭 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
