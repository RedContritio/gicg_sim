-- characters/墨客/墨客_墨意.lua
-- 技能：消耗 2 AP，造成 1 水元素伤害，获得 2 层水云出战角色状态
-- 水云：自身受到伤害 >= 3 时，抵消 1 点，消耗 1 层

local 墨客 = get_char("墨客")
local my_player = 墨客:owner_player()
local my_char = 墨客:owner_char()

local 水云 = declare_counter("水云", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 墨意 = declare_skill(墨客, "墨意", { dices = { water = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 墨意 then return end
  deal_damage(Target.EnemyActive, Element.Water, 1)
  水云:add(2)
end)

on_damage_reduce_buff(function(ctx)
  if ctx.target_player ~= my_player or ctx.target_char ~= my_char then return end
  if 水云:get() <= 0 then return end
  if ctx.value < 3 then return end

  水云:sub(1)
  ctx.value = ctx.value - 1
end)
