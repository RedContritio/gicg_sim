-- characters/天星/天星_枪.lua
-- 普攻：消耗 3 AP，造成 2 物理伤害

local 天星 = get_char("天星")
local my_player = 天星:owner_player()
local my_char = 天星:owner_char()

local 枪 = declare_skill(天星, "枪", { dices = { geo = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 枪 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
