-- characters/砂糖/砂糖_简式风灵作成.lua
-- source: data/cleaned/character/5361_砂糖.yaml#skills[0]
-- 普通攻击 简式风灵作成 — cost {风:1, 无色:2}; 造 1 风元素伤害

local 砂糖 = get_char("砂糖")
local my_player = 砂糖:owner_player()
local my_char = 砂糖:owner_char()

local 简式风灵作成 = declare_skill(砂糖, "简式风灵作成", { dices = { anemo = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 简式风灵作成 then return end
  deal_damage(Target.EnemyActive, Element.Anemo, 1)
end)
