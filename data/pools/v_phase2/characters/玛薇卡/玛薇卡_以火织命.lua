-- characters/玛薇卡/玛薇卡_以火织命.lua
-- source: data/cleaned/character/505479_玛薇卡.yaml#skills[0]
-- 普通攻击 以火织命 — cost {火:1, 无色:2}; 造 2 物理伤害
-- 注: 战意 被动 触发 +1 战意 deferred

local 玛薇卡 = get_char("玛薇卡")
local my_player = 玛薇卡:owner_player()
local my_char = 玛薇卡:owner_char()

local 以火织命 = declare_skill(玛薇卡, "以火织命", { dices = { fire = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 以火织命 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
  -- TODO: 战意 +1
end)
