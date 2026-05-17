-- characters/坎蒂丝/坎蒂丝_流耀枪术_守势.lua
-- source: data/cleaned/character/6804_坎蒂丝.yaml#skills[0]
-- 普通攻击 流耀枪术·守势 — cost {水:1, 无色:2}; 造 2 物理伤害

local 坎蒂丝 = get_char("坎蒂丝")
local my_player = 坎蒂丝:owner_player()
local my_char = 坎蒂丝:owner_char()

local 流耀枪术_守势 = declare_skill(坎蒂丝, "流耀枪术·守势", { dices = { water = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 流耀枪术_守势 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
