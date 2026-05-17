-- characters/凝光/凝光_璇玑屏.lua
-- source: data/cleaned/character/5359_凝光.yaml#skills[1]
-- 元素战技 璇玑屏 — cost {岩:3}; 造 2 岩元素伤害, 生成"璇玑屏"
-- deferred:
--   - "璇玑屏" 出战状态 (我方出战角色受到≥2伤害时,抵消 1 点, 可用次数 2)

local 凝光 = get_char("凝光")
local my_player = 凝光:owner_player()
local my_char = 凝光:owner_char()

local 璇玑屏 = declare_skill(凝光, "璇玑屏", { dices = { geo = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 璇玑屏 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 2)
  -- TODO: 生成 "璇玑屏" 出战状态
end)
