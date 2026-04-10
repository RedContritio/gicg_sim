-- characters/墨客/墨客_水龙吟.lua
-- 大招：消耗 3 AP + 2 能量，获得 2 层泼墨出战角色状态
-- 泼墨：每次对敌方造成技能伤害时，额外造成 2 水伤害，持续 2 回合

local 墨客 = get_char("墨客")
local 泼墨 = declare_counter("泼墨", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 泼墨_rounds = declare_counter("泼墨_rounds", Scope.ActiveStatus, 0, { min = 0, max = 10 })
local 水龙吟 = declare_skill(墨客, "水龙吟", 3, 2)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 水龙吟 then return end
  泼墨:set(2)
  泼墨_rounds:set(2)
end)

-- 泼墨触发：己方出战角色技能伤害后，额外造成 2 水伤害
on_after_damage(function(ctx)
  if ctx.actor_player ~= 墨客:owner_player() then return end
  if get_active_char(ctx.actor_player) ~= ctx.actor_char then return end
  if ctx.source ~= Source.Skill then return end
  if 泼墨:get() <= 0 then return end

  deal_damage(Target.EnemyActive, Element.Water, 2, { source = Source.Status })
  泼墨:sub(1)
end)

-- 持续时间衰减
on_round_end_decay(function(ctx)
  if 泼墨_rounds:get() > 0 then
    泼墨_rounds:sub(1)
    if 泼墨_rounds:get() <= 0 then
      泼墨:set(0)
    end
  end
end)
