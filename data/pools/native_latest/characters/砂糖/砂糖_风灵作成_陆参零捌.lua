-- 官方资料5361：先伤害，再强制切换到前一个存活角色。
local 砂糖 = get_char("砂糖")
local my_player = 砂糖:owner_player()
local my_char = 砂糖:owner_char()

local 风灵作成_陆参零捌 = declare_skill(砂糖, "风灵作成·陆参零捌", { dices = { anemo = 3 } })

on_skill_use(function(ctx)
  if ctx.actor_player ~= my_player or ctx.actor_char ~= my_char then return end
  if ctx.skill_index ~= 风灵作成_陆参零捌 then return end
  deal_damage(Target.EnemyActive, Element.Anemo, 3)
  force_switch_previous(Player.Enemy)
end)
