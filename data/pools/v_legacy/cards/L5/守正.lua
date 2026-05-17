local ref = declare_card("守正", { dices = { water = 3 }, energy = 2 }, { battle_action = true, requires_char = "墨客" })
local 墨客 = get_char("墨客")
local 水龙吟_skill = get_skill(墨客, "水龙吟")
local 泼墨 = get_counter("泼墨", Scope.ActiveStatus)
local 水云 = get_counter("水云", Scope.ActiveStatus)

local active = declare_counter("守正_active", Scope.Self, 0, { min = 0, max = 1 })
local 正气 = declare_counter("正气", Scope.Self, 0, { min = 0, max = 2 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if get_active_char(ctx.actor_player) ~= 墨客:owner_char() then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
  invoke_skill(水龙吟_skill)
end)

-- 守正下水龙吟额外先造成 2 水伤害
on_skill_use(function(ctx)
  if ctx.skill_index ~= 水龙吟_skill then return end
  if active:get() <= 0 then return end
  deal_damage(Target.EnemyActive, Element.Water, 2)
end)

-- 泼墨被消耗时获得正气
on_after_write(泼墨, Op.Sub, function(ctx)
  if active:get() <= 0 then return end
  正气:add(1)
end)

-- 水云被消耗前：正气替代
on_before_write(水云, Op.Sub, function(ctx)
  if active:get() <= 0 then return end
  if 正气:get() <= 0 then return end
  正气:sub(1)
  cancel()
end)

-- 正气回合结束衰减（召唤物结算之后）
on_round_end_decay(function(ctx)
  if 正气:get() > 0 then
    正气:sub(1)
  end
end)
