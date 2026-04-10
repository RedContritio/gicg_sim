local 天星 = get_char("天星")

local 石化 = declare_counter("石化", Scope.PerChar, 0, { min = 0, max = 1 })
local 石化_acted = declare_counter("石化_acted", Scope.PerChar, 0, { min = 0, max = 10 })

local 天星大招 = declare_skill(天星, "天星", 3, 3)

on_skill_use(function(ctx)
  if ctx.skill_index ~= 天星大招 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 2)
  local enemy = get_active_char(Player.Enemy)
  石化:set_at(Player.Enemy, enemy, 1)
  石化_acted:set_at(Player.Enemy, enemy, 0)
end)

on_round_start(function(ctx)
  石化_acted:fill_all(Player.Enemy, 0)
end)

-- 石化角色出战时，每次行动计数 +1
on_before_turn_flip(function(ctx)
  local active = get_active_char(ctx.actor_player)
  if 石化:get_at(ctx.actor_player, active) <= 0 then return end
  石化_acted:add_at(ctx.actor_player, active, 1)
end)

-- 第二次行动时只能结束回合
on_action_check(function(ctx)
  local active = get_active_char(ctx.actor_player)
  if 石化:get_at(ctx.actor_player, active) <= 0 then return end
  if 石化_acted:get_at(ctx.actor_player, active) < 1 then return end
  if ctx.action_kind ~= ActionKind.EndTurn then
    ctx.playable = false
  end
end)

-- 石化触发后消耗
on_round_end(function(ctx)
  local active = get_active_char(Player.Enemy)
  if 石化:get_at(Player.Enemy, active) > 0 and 石化_acted:get_at(Player.Enemy, active) >= 1 then
    石化:sub_at(Player.Enemy, active, 1)
  end
end)
