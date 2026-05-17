-- 轻击：1 fire + Any=2,2 Physical 伤害。基础技能,需要 1 火(spec)+ 2 任意,
-- 在 Stage 0 标配 fix_dice [2F+2I+2W+2E] 下可打 2 次(2F 消尽)。
local 测试角色D = get_char("测试角色D")
local my_player = 测试角色D:owner_player()
local my_char = 测试角色D:owner_char()

local 轻击 = declare_skill(测试角色D, "轻击", { dices = { fire = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 轻击 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
