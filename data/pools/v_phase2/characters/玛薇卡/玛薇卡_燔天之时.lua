-- characters/玛薇卡/玛薇卡_燔天之时.lua
-- source: data/cleaned/character/505479_玛薇卡.yaml#skills[2]
-- 元素爆发 燔天之时 — cost {火:4} + 能量:3; 造 4 火元素伤害 (若消耗 6 战意 +附"死生之炉")
-- deferred:
--   - 消耗 6 战意条件 + 附"死生之炉" 出战状态

local 玛薇卡 = get_char("玛薇卡")
local my_player = 玛薇卡:owner_player()
local my_char = 玛薇卡:owner_char()

local 燔天之时 = declare_skill(玛薇卡, "燔天之时", { dices = { fire = 4 }, energy = 3 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 燔天之时 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 4)
  -- TODO: 消耗 6 战意 → 附"死生之炉"
end)
