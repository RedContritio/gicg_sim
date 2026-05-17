-- 突刺：Any=2,1 Physical 伤害。完全无色成本,fire 耗尽后的 fallback。
-- damage/dice 比最低(0.5),但在 fire-starved 状态下是唯一可用伤害技。
-- agent 应学会"轻击优先(火充足时) → 突刺兜底(火耗尽时)"的排序。
local 测试角色D = get_char("测试角色D")
local my_player = 测试角色D:owner_player()
local my_char = 测试角色D:owner_char()

local 突刺 = declare_skill(测试角色D, "突刺", { dices = { any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 突刺 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 1)
end)
