-- characters/赤蝶/赤蝶_枪.lua
-- 普攻：消耗 3 AP，造成 2 物理伤害

local 赤蝶 = get_char("赤蝶")
-- Mirror-match fix (#152): capture load-time owner and filter the
-- on_skill_use hook to events produced by this binding only. Without
-- it, mirror loading (赤蝶 vs 赤蝶) registers the hook twice and a
-- single 枪 cast triggers deal_damage from both copies → 4 damage
-- instead of 2.
local my_player = 赤蝶:owner_player()
local my_char = 赤蝶:owner_char()

local 枪 = declare_skill(赤蝶, "枪", { dices = { fire = 1, any = 2 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 枪 then return end
  deal_damage(Target.EnemyActive, Element.Physical, 2)
end)
