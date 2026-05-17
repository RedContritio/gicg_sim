-- characters/凯亚/凯亚_凛冽轮舞.lua
-- source: data/cleaned/character/5375_凯亚.yaml#skills[2]
-- 元素爆发 凛冽轮舞 — cost {冰:4} + 能量:2; 造 1 冰元素伤害, 生成"寒冰之棱"
-- deferred:
--   - "寒冰之棱" 召唤物/出战状态 (ref kaeya.ts: 切换角色后造 2 冰伤,可用次数 3)
--     未实现 — 当前 lua 只造 1 冰伤,寒冰之棱触发机制后续补

local 凯亚 = get_char("凯亚")
local my_player = 凯亚:owner_player()
local my_char = 凯亚:owner_char()

local 凛冽轮舞 = declare_skill(凯亚, "凛冽轮舞", { dices = { ice = 4 }, energy = 2 })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 凛冽轮舞 then return end
  deal_damage(Target.EnemyActive, Element.Ice, 1)
  -- TODO: 生成 "寒冰之棱" 出战状态 (可用次数 3, on_switch_active 造 2 冰伤)
end)
