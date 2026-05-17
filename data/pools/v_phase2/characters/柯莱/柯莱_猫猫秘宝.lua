-- characters/柯莱/柯莱_猫猫秘宝.lua
-- source: data/cleaned/character/5357_柯莱.yaml#skills[2]
-- 元素爆发 猫猫秘宝 — cost {草:3} + 能量:2; 造 2 草元素伤害 + 召唤"柯里安巴"
-- deferred:
--   - "柯里安巴" 召唤物 (结束阶段 2 草, 可用次数 2)

local 柯莱 = get_char("柯莱")
local my_player = 柯莱:owner_player()
local my_char = 柯莱:owner_char()

local 猫猫秘宝 = declare_skill(柯莱, "猫猫秘宝", { dices = { dendro = 3 }, energy = 2 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 猫猫秘宝 then return end
  deal_damage(Target.EnemyActive, Element.Dendro, 2)
  -- TODO: 召唤 "柯里安巴" (结束阶段 2 草, 可用次数 2)
end)
