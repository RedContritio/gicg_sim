-- 纯色技能:消耗 3 fire,造成 3 fire 伤害。cost 没有 Any 部分,只有 Specific —
-- 这让 dice 管理的边际价值变陡:差 1 火 → 整个 3 伤跑不出来 → tune 成为
-- 跨门槛动作。Element.Fire 会把火附着到目标,与 神秘水流 水伤结合触发
-- 蒸发(engine 侧的真实反应 +2)。
local 测试角色C = get_char("测试角色C")
local my_player = 测试角色C:owner_player()
local my_char = 测试角色C:owner_char()

local 焰爆 = declare_skill(测试角色C, "焰爆", { dices = { fire = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 焰爆 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 3)
end)
