-- characters/凯亚/凯亚_霜袭.lua
-- source: data/cleaned/character/5375_凯亚.yaml#skills[1]
-- 元素战技 霜袭 — cost {冰:3}; 造 3 冰元素伤害

local 凯亚 = get_char("凯亚")
local my_player = 凯亚:owner_player()
local my_char = 凯亚:owner_char()

local 霜袭 = declare_skill(凯亚, "霜袭", { dices = { ice = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 霜袭 then return end
  deal_damage(Target.EnemyActive, Element.Ice, 3)
end)
