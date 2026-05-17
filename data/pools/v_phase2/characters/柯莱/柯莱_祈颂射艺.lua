-- characters/柯莱/柯莱_祈颂射艺.lua
-- source: data/cleaned/character/5357_柯莱.yaml#skills[0]
-- 普通攻击 祈颂射艺 — cost {草:1, 无色:2}; 造 2 物理伤害

local 柯莱 = get_char("柯莱")
local my_player = 柯莱:owner_player()
local my_char = 柯莱:owner_char()

local 祈颂射艺 = declare_skill(柯莱, "祈颂射艺", { dices = { dendro = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 祈颂射艺 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
