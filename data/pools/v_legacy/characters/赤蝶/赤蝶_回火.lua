-- characters/赤蝶/赤蝶_回火.lua
-- 大招：消耗 3 AP + 3 能量，对敌方出战角色造成 4 火元素伤害
-- 蝶火条件治疗由 赤蝶_蝶火.lua 负责

local 赤蝶 = get_char("赤蝶")
local my_player = 赤蝶:owner_player()
local my_char = 赤蝶:owner_char()

local 回火 = declare_skill(赤蝶, "回火", { dices = { fire = 3 }, energy = 3 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 回火 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 4)
end)
