-- characters/坎蒂丝/坎蒂丝_圣仪_苍鹭庇卫.lua
-- source: data/cleaned/character/6804_坎蒂丝.yaml#skills[1]
-- 元素战技 圣仪·苍鹭庇卫 — cost {水:3}; 本角色附"苍鹭护盾"并准备"苍鹭震击"
-- deferred:
--   - "苍鹭护盾" status + "苍鹭震击" prepare_skill 完整机制 (ADR-0012)
--     当前 lua 仅造 1 水伤代表"已使用",避免空 skill 让 RL 学不出意义

local 坎蒂丝 = get_char("坎蒂丝")
local my_player = 坎蒂丝:owner_player()
local my_char = 坎蒂丝:owner_char()

local 圣仪_苍鹭庇卫 = declare_skill(坎蒂丝, "圣仪·苍鹭庇卫", { dices = { water = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 圣仪_苍鹭庇卫 then return end
  -- TODO: 附"苍鹭护盾" + 准备"苍鹭震击" (prepare_skill, ref candace.ts: 2 水 + 附 status)
  deal_damage(Target.EnemyActive, Element.Water, 1)
end)
