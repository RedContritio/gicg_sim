-- characters/柯莱/柯莱_拂花偈叶.lua
-- source: data/cleaned/character/5357_柯莱.yaml#skills[1]
-- 元素战技 拂花偈叶 — cost {草:3}; 造 3 草元素伤害

local 柯莱 = get_char("柯莱")
local my_player = 柯莱:owner_player()
local my_char = 柯莱:owner_char()

local 拂花偈叶 = declare_skill(柯莱, "拂花偈叶", { dices = { dendro = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 拂花偈叶 then return end
  deal_damage(Target.EnemyActive, Element.Dendro, 3)
end)
