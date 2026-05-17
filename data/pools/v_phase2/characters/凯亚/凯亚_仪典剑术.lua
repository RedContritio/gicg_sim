-- characters/凯亚/凯亚_仪典剑术.lua
-- source: data/cleaned/character/5375_凯亚.yaml#skills[0]
-- 普通攻击 仪典剑术 — cost {冰:1, 无色:2}; 造 2 物理伤害

local 凯亚 = get_char("凯亚")
local my_player = 凯亚:owner_player()
local my_char = 凯亚:owner_char()

local 仪典剑术 = declare_skill(凯亚, "仪典剑术", { dices = { ice = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 仪典剑术 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
