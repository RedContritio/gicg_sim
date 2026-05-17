-- characters/凝光/凝光_天权崩玉.lua
-- source: data/cleaned/character/5359_凝光.yaml#skills[2]
-- 元素爆发 天权崩玉 — cost {岩:3} + 能量:3; 造 6 岩元素伤害 (璇玑屏在场 +2)
-- deferred:
--   - +2 条件检查 (璇玑屏 status 在场时本伤害 +2)

local 凝光 = get_char("凝光")
local my_player = 凝光:owner_player()
local my_char = 凝光:owner_char()

local 天权崩玉 = declare_skill(凝光, "天权崩玉", { dices = { geo = 3 }, energy = 3 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 天权崩玉 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 6)
  -- TODO: 璇玑屏 在场 +2 加成
end)
