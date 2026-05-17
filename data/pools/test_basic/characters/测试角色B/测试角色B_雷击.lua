-- B 的技能：消耗 3 fire (跨元素 — 用户例子里 B 的 cost 是 A 的元素色),
-- 造成 5 物理伤害。
-- 跨元素 cost 是测试设计的一部分：让 greedy 看到 value=5 的高分动作但
-- 在典型 pool (few fire, lots of non-fire) 下无法直接凑齐 3 fire,
-- 从而暴露"greedy 眼里最优 ≠ 能做到"的情形。
local 测试角色B = get_char("测试角色B")
local my_player = 测试角色B:owner_player()
local my_char = 测试角色B:owner_char()

local 雷击 = declare_skill(测试角色B, "雷击", { dices = { fire = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 雷击 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 5)
end)
