-- characters/坎蒂丝/坎蒂丝_圣仪_灰鸰衒潮.lua
-- source: data/cleaned/character/6804_坎蒂丝.yaml#skills[2]
-- 元素爆发 圣仪·灰鸰衒潮 — cost {水:3} + 能量:2; 造 2 水元素伤害 + 生成"赤冕祝祷"
-- deferred:
--   - "赤冕祝祷" 出战状态 (普攻+1 / 物理转水 / 切换造 1 水, 持续 2 回合)

local 坎蒂丝 = get_char("坎蒂丝")
local my_player = 坎蒂丝:owner_player()
local my_char = 坎蒂丝:owner_char()

local 圣仪_灰鸰衒潮 = declare_skill(坎蒂丝, "圣仪·灰鸰衒潮", { dices = { water = 3 }, energy = 2 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 圣仪_灰鸰衒潮 then return end
  deal_damage(Target.EnemyActive, Element.Water, 2)
  -- TODO: 生成"赤冕祝祷" 出战状态
end)
