-- characters/砂糖/砂糖_禁_风灵作成_柒伍同构贰型.lua
-- source: data/cleaned/character/5361_砂糖.yaml#skills[2]
-- 元素爆发 禁·风灵作成·柒伍同构贰型 — cost {风:3} + 能量:2; 造 1 风元素伤害 + 召唤"大型风灵"
-- deferred:
--   - "大型风灵" 召唤物 (结束阶段 2 风, 可用次数 3)

local 砂糖 = get_char("砂糖")
local my_player = 砂糖:owner_player()
local my_char = 砂糖:owner_char()

local 禁_风灵作成_柒伍同构贰型 = declare_skill(砂糖, "禁·风灵作成·柒伍同构贰型", { dices = { anemo = 3 }, energy = 2 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 禁_风灵作成_柒伍同构贰型 then return end
  deal_damage(Target.EnemyActive, Element.Anemo, 1)
  -- TODO: 召唤 "大型风灵" (结束阶段 2 风, 可用次数 3)
end)
