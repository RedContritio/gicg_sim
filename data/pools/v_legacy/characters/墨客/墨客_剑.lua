-- characters/墨客/墨客_剑.lua
-- 普攻：消耗 3 AP，造成 2 物理伤害

local 墨客 = get_char("墨客")
local my_player = 墨客:owner_player()
local my_char = 墨客:owner_char()

local 剑 = declare_skill(墨客, "剑", { dices = { water = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 剑 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
