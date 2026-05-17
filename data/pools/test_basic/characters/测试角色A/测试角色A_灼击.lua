-- 普攻：消耗 1 fire + 2 任意，造成 2 fire 伤害。Element.Fire attaches
-- fire to the target on hit — this is intentional: scenarios that
-- use the reaction-based 神秘水流 card rely on the bootstrap's first
-- action (灼击 or 焰爆) to seed fire on the enemy so water damage
-- triggers 蒸发 (+2) naturally. Fire-on-fire-attached is a no-op
-- reaction (just re-attaches), so scenarios without water-dealing
-- cards see unchanged damage numbers.
local 测试角色A = get_char("测试角色A")
local my_player = 测试角色A:owner_player()
local my_char = 测试角色A:owner_char()

local 灼击 = declare_skill(测试角色A, "灼击", { dices = { fire = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 灼击 then return end
  deal_damage(Target.EnemyActive, Element.Fire, 2)
end)
