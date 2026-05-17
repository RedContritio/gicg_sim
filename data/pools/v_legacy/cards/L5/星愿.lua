local ref = declare_card("星愿", { dices = { geo = 5 } }, { battle_action = true, requires_char = "天星" })
local 天星 = get_char("天星")
local 玉璋_skill = get_skill(天星, "玉璋")
local 玉璋护盾 = get_counter("玉璋护盾", Scope.ActiveStatus)
local 岩脊_rounds = get_counter("岩脊_rounds", Scope.ActiveStatus)
local 枪 = get_skill(天星, "枪")
local 岩脊_skill = get_skill(天星, "岩脊")

local active = declare_counter("星愿_active", Scope.Self, 0, { min = 0, max = 1 })
local pending_heal = declare_counter("星愿_pending", Scope.PerPlayer, 0, { min = 0, max = 1 })

local 岩脊2_rounds = declare_counter("岩脊2_rounds", Scope.ActiveStatus, 0, { min = 0, max = 2, tag = Tag.Summon })

on_action_check(function(ctx)
  if ctx.action_kind ~= ActionKind.Card then return end
  if ctx.card_ref ~= ref then return end
  if get_active_char(ctx.actor_player) ~= 天星:owner_char() then
    ctx.playable = false
  end
end)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
  invoke_skill(玉璋_skill)
end)

-- 枪命中+玉璋护盾存在 → 触发 pending heal
on_after_damage(function(ctx)
  if active:get() <= 0 then return end
  if ctx.skill_index ~= 枪 then return end
  if not ctx.hit then return end
  if 玉璋护盾:get() <= 0 then return end
  pending_heal:add(1)
end)

-- 按角色顺序注册 heal hook：天星 → next → next
-- 天星自己
on_after_write(pending_heal, Op.Add, function(ctx)
  if pending_heal:get() <= 0 then return end
  local p = 天星:owner_player()
  local hp = 天星:hp()
  if hp:get() > 0 and hp:get() < hp:cmax() then
    heal(Target.OwnActive, 1)
    pending_heal:set(0)
  end
end)

-- 下一个角色
on_after_write(pending_heal, Op.Add, function(ctx)
  if pending_heal:get() <= 0 then return end
  local p = 天星:owner_player()
  local c1 = get_next_char(p, 天星:owner_char())
  if c1 == 天星:owner_char() then return end
  local ch = _char_by_slot[p][c1]
  if ch and ch.hp:get() > 0 and ch.hp:get() < ch.hp:cmax() then
    ch.hp:add(1)
    pending_heal:set(0)
  end
end)

-- 再下一个角色
on_after_write(pending_heal, Op.Add, function(ctx)
  if pending_heal:get() <= 0 then return end
  local p = 天星:owner_player()
  local c1 = get_next_char(p, 天星:owner_char())
  if c1 == 天星:owner_char() then return end
  local c2 = get_next_char(p, c1)
  if c2 == 天星:owner_char() then return end
  local ch = _char_by_slot[p][c2]
  if ch and ch.hp:get() > 0 and ch.hp:get() < ch.hp:cmax() then
    ch.hp:add(1)
    pending_heal:set(0)
  end
end)

-- 刷新岩脊时优先寿命最短的
on_skill_use(function(ctx)
  if active:get() <= 0 then return end
  if ctx.skill_index ~= 岩脊_skill then return end

  if 岩脊_rounds:get() > 0 and 岩脊2_rounds:get() > 0 then
    if 岩脊2_rounds:get() < 岩脊_rounds:get() then
      玉璋护盾:add(1)
      岩脊2_rounds:set(2)
    end
  elseif 岩脊2_rounds:get() <= 0 and 岩脊_rounds:get() > 0 then
    岩脊2_rounds:set(2)
  end
end)

on_round_end_post_summon(function(ctx)
  if 岩脊2_rounds:get() <= 0 then return end
  deal_damage(Target.EnemyActive, Element.Geo, 1, { source = Source.Summon })
end)

on_round_end_decay(function(ctx)
  if 岩脊2_rounds:get() > 0 then
    岩脊2_rounds:sub(1)
    if 岩脊2_rounds:get() <= 0 then
      玉璋护盾:add(1)
    end
  end
end)
