local ref = declare_card("蝶鳞", { dices = { fire = 3 } }, { battle_action = true, requires_char = "赤蝶" })
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
on_after_damage({ order = active }, function(ctx)
  if ctx.source ~= Source.Skill then return end
  if active:get() <= 0 then return end
  if 蝶火_active:get() <= 0 then return end
  if ctx.skill_index ~= 枪 then return end
  if not ctx.hit then return end
  local victim = _char_by_slot[ctx.target_player][ctx.target_char]
  if not victim or not victim:alive() then return end
  蝶印:set_at(ctx.target_player, ctx.target_char, 1)
end)

-- 修改回火已经满足低血量条件的治疗，避免基础治疗先抬高生命后漏判。
on_before_heal({ order = active }, function(ctx)
  if ctx.source ~= Source.Skill then return end
  if ctx.skill_index ~= 回火 then return end
  if active:get() <= 0 or 蝶火_active:get() <= 0 then return end
  ctx.value = ctx.value + 1
end)

-- 回火命中带蝶印的敌人时，仅追加一次状态伤害。
on_after_damage({ order = active }, function(ctx)
  if ctx.source ~= Source.Skill then return end
  if active:get() <= 0 then return end
  if ctx.skill_index ~= 回火 then return end
  if 蝶火_active:get() <= 0 then return end

  local victim = _char_by_slot[ctx.target_player][ctx.target_char]
  if not victim or not victim:alive() then return end
  if 蝶印:get_at(ctx.target_player, ctx.target_char) > 0 then
    deal_damage(victim, Element.Fire, 1, { source = Source.Status })
  end
end)

-- 用户确认：后台角色的蝶印也在回合末造成 1 火，然后清除。
-- 每枚印独立入队，跨双方按印的产生顺序；伤害归属施加方。
on_round_end({ order = 蝶印, order_on = "target" }, function(ctx)
  local victim = _char_by_slot[ctx.actor_player][ctx.actor_char]
  local source_player = 1 - ctx.actor_player
  local source_char = _char_by_slot[source_player][get_active_char(source_player)]
  if victim and victim:alive() then
    deal_damage(victim, Element.Fire, 1, { source = Source.Status, actor = source_char })
  end
  蝶印:set_at(ctx.actor_player, ctx.actor_char, 0)
end)

register_buff(蝶印, { remove_on_death = true })
register_buff(active)
