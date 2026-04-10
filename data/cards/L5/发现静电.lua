local ref = declare_card("发现静电", 3, { battle_action = true })
local 刻师傅 = get_char("刻师傅")
local 刻印 = get_skill(刻师傅, "刻印")
local 剑 = get_skill(刻师傅, "剑")
local 雷暴 = get_skill(刻师傅, "雷暴")

local active = declare_counter("静电体_active", Scope.Self, 0, { min = 0, max = 1 })
local 负电 = declare_counter("负电", Scope.PerChar, 0, { min = 0, max = 2 })
local 正电 = declare_counter("正电", Scope.PerChar, 0, { min = 0, max = 2 })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if get_active_char(ctx.actor_player) ~= 刻师傅:owner_char() then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
  invoke_skill(刻印)
end)

-- 刻印：敌方出战角色 +1 负电
on_skill_use(function(ctx)
  if active:get() <= 0 then return end
  if ctx.skill_index ~= 刻印 then return end
  local enemy_active = get_active_char(Player.Enemy)
  负电:add_at(Player.Enemy, enemy_active, 1)
end)

-- 剑/雷暴：敌方出战角色 +1 正电
on_skill_use(function(ctx)
  if active:get() <= 0 then return end
  if ctx.skill_index ~= 剑 and ctx.skill_index ~= 雷暴 then return end
  local enemy_active = get_active_char(Player.Enemy)
  正电:add_at(Player.Enemy, enemy_active, 1)
end)

-- 复刻使用时的正/负电交互
local 复刻_ref = get_card("复刻")

on_action_prepare(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= 复刻_ref then return end
  if active:get() <= 0 then return end
  local enemy_active = get_active_char(Player.Enemy)
  local pos = 正电:get_at(Player.Enemy, enemy_active)
  local neg = 负电:get_at(Player.Enemy, enemy_active)
  if pos > neg then
    ctx.ap_cost = ctx.ap_cost - 1
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= 复刻_ref then return end
  if active:get() <= 0 then return end
  local enemy_active = get_active_char(Player.Enemy)
  local pos = 正电:get_at(Player.Enemy, enemy_active)
  local neg = 负电:get_at(Player.Enemy, enemy_active)
  if pos > 0 and pos == neg then
    正电:sub_at(Player.Enemy, enemy_active, 1)
    负电:sub_at(Player.Enemy, enemy_active, 1)
    heal(Target.OwnActive, 1)
  elseif pos > neg then
    正电:sub_at(Player.Enemy, enemy_active, 1)
    负电:sub_at(Player.Enemy, enemy_active, 1)
  end
end)
