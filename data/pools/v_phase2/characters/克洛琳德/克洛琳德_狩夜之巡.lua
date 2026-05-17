-- characters/克洛琳德/克洛琳德_狩夜之巡.lua
-- source: data/cleaned/character/503960_克洛琳德.yaml#skills[1]
-- 元素战技 狩夜之巡 — cost {雷:2}; 附"夜巡" + 移除所有"生命之契" → 按数造雷伤+治疗(≤4)
-- deferred:
--   - "夜巡" 出战状态 (1 回合,普攻物理→雷 + 自附 2 契)
--   - "生命之契" 计数 / 移除 / 转伤害+治疗 (≤4)
-- 简化实现: 仅造 1 雷代表"已使用"

local 克洛琳德 = get_char("克洛琳德")
local my_player = 克洛琳德:owner_player()
local my_char = 克洛琳德:owner_char()

local 狩夜之巡 = declare_skill(克洛琳德, "狩夜之巡", { dices = { electro = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 狩夜之巡 then return end
  deal_damage(Target.EnemyActive, Element.Electro, 1)
  -- TODO: 移除"生命之契" 计 N → 造 N 雷 (≤4) + 治疗 N (≤4); 附"夜巡" status
end)
