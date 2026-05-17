-- characters/砂糖/砂糖_风灵作成_陆参零捌.lua
-- source: data/cleaned/character/5361_砂糖.yaml#skills[1]
-- 元素战技 风灵作成·陆参零捌 — cost {风:3}; 造 3 风元素伤害 + 强制敌方出战切换
-- deferred:
--   - 强制切换 (force-switch 敌方出战角色)

local 砂糖 = get_char("砂糖")
local my_player = 砂糖:owner_player()
local my_char = 砂糖:owner_char()

local 风灵作成_陆参零捌 = declare_skill(砂糖, "风灵作成·陆参零捌", { dices = { anemo = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 风灵作成_陆参零捌 then return end
  deal_damage(Target.EnemyActive, Element.Anemo, 3)
  -- TODO: 强制切换敌方出战角色
end)
