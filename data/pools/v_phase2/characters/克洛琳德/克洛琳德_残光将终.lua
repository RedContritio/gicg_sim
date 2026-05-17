-- characters/克洛琳德/克洛琳德_残光将终.lua
-- source: data/cleaned/character/503960_克洛琳德.yaml#skills[2]
-- 元素爆发 残光将终 — cost {雷:3} + 能量:2; 造 3 雷元素伤害 + 自身附 4 层"生命之契"
-- deferred:
--   - "生命之契" counter add 4 (status)

local 克洛琳德 = get_char("克洛琳德")
local my_player = 克洛琳德:owner_player()
local my_char = 克洛琳德:owner_char()

local 残光将终 = declare_skill(克洛琳德, "残光将终", { dices = { electro = 3 }, energy = 2 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 残光将终 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 3)
  -- TODO: 自附 4 层 "生命之契"
end)
