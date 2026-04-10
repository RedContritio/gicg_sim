local ref = declare_card("蝶鳞", 3, { battle_action = true })
local 赤蝶 = get_char("赤蝶")
local 蝶火_active = get_counter("蝶火_active", Scope.Self)
local 蝶火_skill = get_skill(赤蝶, "蝶火")

local active = declare_counter("蝶鳞_active", Scope.Self, 0, { min = 0, max = 1 })
local 蝶印 = declare_counter("蝶印", Scope.PerChar, 0, { min = 0, max = 1 })

local 枪 = get_skill(赤蝶, "枪")
local 回火 = get_skill(赤蝶, "回火")

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if get_active_char(ctx.actor_player) ~= 赤蝶:owner_char() then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
  invoke_skill(蝶火_skill)
end)

-- 枪造成伤害时给敌方附加蝶印
on_after_damage(function(ctx)
  if active:get() <= 0 then return end
  if 蝶火_active:get() <= 0 then return end
  if ctx.skill_index ~= 枪 then return end
  if not ctx.hit then return end
  local enemy_active = get_active_char(Player.Enemy)
  蝶印:set_at(Player.Enemy, enemy_active, 1)
end)

-- 回火额外 +1 治疗（原有 hook 给 2+N，蝶鳞额外 +1 = 3+N）
-- 同时如果敌方有蝶印，额外 1 火伤害
on_after_damage(function(ctx)
  if active:get() <= 0 then return end
  if ctx.skill_index ~= 回火 then return end
  if 蝶火_active:get() <= 0 then return end

  local hp = 赤蝶:hp():get()
  if hp < 赤蝶:hp():cmax() / 2 then
    heal(Target.OwnActive, 1)
  end

  local enemy_active = get_active_char(Player.Enemy)
  if 蝶印:get_at(Player.Enemy, enemy_active) > 0 then
    deal_damage(Target.EnemyActive, Element.Fire, 1, { source = Source.Status })
  end
end)

-- 蝶印：回合结束造成 1 火伤害并清除
on_round_end(function(ctx)
  local active_c = get_active_char(Player.Enemy)
  if 蝶印:get_at(Player.Enemy, active_c) > 0 then
    蝶印:set_at(Player.Enemy, active_c, 0)
    deal_damage(Target.EnemyActive, Element.Fire, 1, { source = Source.Status })
  end
end)
