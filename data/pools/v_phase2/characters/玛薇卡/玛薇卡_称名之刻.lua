-- characters/玛薇卡/玛薇卡_称名之刻.lua
-- source: data/cleaned/character/505479_玛薇卡.yaml#skills[1]
-- 元素战技 称名之刻 — cost {火:3}; 造 1 火 + 生成 1 张驰轮车手牌 + 附"诸火武装·焚曜之环"
-- deferred:
--   - 生成驰轮车手牌 (玛薇卡专属 specialty card pool)
--   - "诸火武装·焚曜之环" 出战状态
--   - 战意 +1

local 玛薇卡 = get_char("玛薇卡")
local my_player = 玛薇卡:owner_player()
local my_char = 玛薇卡:owner_char()

local 称名之刻 = declare_skill(玛薇卡, "称名之刻", { dices = { fire = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 称名之刻 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 1)
  -- TODO: 生成 1 张驰轮车手牌 + 附"诸火武装·焚曜之环"
end)
