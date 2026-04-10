-- characters/墨客/墨客_剑.lua
-- 普攻：消耗 3 AP，造成 2 物理伤害

local 墨客 = get_char("墨客")
local 剑 = declare_skill(墨客, "剑", 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 剑 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
