-- characters/凝光/凝光_千金掷.lua
-- source: data/cleaned/character/5359_凝光.yaml#skills[0]
-- 普通攻击 千金掷 — cost {岩:1, 无色:2}; 造 1 岩元素伤害

local 凝光 = get_char("凝光")
local my_player = 凝光:owner_player()
local my_char = 凝光:owner_char()

local 千金掷 = declare_skill(凝光, "千金掷", { dices = { geo = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 千金掷 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 1)
end)
