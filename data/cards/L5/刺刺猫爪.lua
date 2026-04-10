local ref = declare_card("刺刺猫爪", 3, { battle_action = true })
local 猫咪 = get_char("猫咪")
local 猫爪护盾 = get_counter("猫爪护盾", Scope.ActiveStatus)
local 猫爪_skill = get_skill(猫咪, "猫爪护盾")

local active = declare_counter("刺刺猫爪_active", Scope.Self, 0, { min = 0, max = 1 })
local trigger_count = declare_counter("刺刺猫爪_trigger", Scope.Self, 0, { min = 0, max = 2 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if get_active_char(ctx.actor_player) ~= 猫咪:owner_char() then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
  invoke_skill(猫爪_skill)
end)

on_after_write(猫爪护盾, Op.Sub, function(ctx)
  if active:get() <= 0 then return end
  if trigger_count:get() >= 2 then return end
  trigger_count:add(1)
  if 猫爪护盾:get() > 0 then
    猫爪护盾:add(1)
  else
    deal_damage(Target.EnemyActive, Element.None, 1, { penetrate = true })
  end
end)

on_round_start(function(ctx)
  trigger_count:set(0)
end)
