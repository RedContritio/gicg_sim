-- 重击：3 fire,3 Physical 伤害。纯色成本 → Stage 0 默认 fix_dice
-- (2F) 下付不起,agent 需要学会"重击不可选"而不是一直追高 damage。
-- 若后续实验换 fix_dice 提供 3F+,agent 会发现 重击 的 damage/dice
-- 最优 (3/3=1.0 vs 轻击 2/3=0.67 vs 突刺 1/2=0.5)。
local 测试角色D = get_char("测试角色D")
local my_player = 测试角色D:owner_player()
local my_char = 测试角色D:owner_char()

local 重击 = declare_skill(测试角色D, "重击", { dices = { fire = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 重击 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 3)
end)
