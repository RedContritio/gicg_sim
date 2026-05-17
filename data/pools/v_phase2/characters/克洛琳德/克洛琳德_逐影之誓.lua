-- characters/克洛琳德/克洛琳德_逐影之誓.lua
-- source: data/cleaned/character/503960_克洛琳德.yaml#skills[0]
-- 普通攻击 逐影之誓 — cost {雷:1, 无色:2}; 造 1 物理伤害
-- 注: 附"夜巡"时物理→雷 + 普攻后自附 2 契 (条件分支 deferred)

local 克洛琳德 = get_char("克洛琳德")
local my_player = 克洛琳德:owner_player()
local my_char = 克洛琳德:owner_char()

local 逐影之誓 = declare_skill(克洛琳德, "逐影之誓", { dices = { electro = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 逐影之誓 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 1)
  -- TODO: 附"夜巡"时 物理→雷 + 自附 2 契
end)
