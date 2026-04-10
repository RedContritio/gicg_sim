local ref = declare_card("玄冰", 1)
local active = declare_counter("玄冰_active", Scope.PerPlayer, 0, { min = 0, max = 1 })
local attached_ice = get_counter("attached_ice", Scope.PerChar)
local attached_electro = get_counter("attached_electro", Scope.PerChar)

on_card_play(function(ctx)
  if ctx.card_ref ~= ref then return end
  active:set(1)
end)

-- 比超导(默认优先级0)更高，拦截超导条件
on_reaction_damage(1, function(ctx)
  if active:get() <= 0 then return end

  local tp, tc = ctx.target_player, ctx.target_char
  local triggered = false

  if ctx.element == Element.Electro and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Ice and attached_electro:get_at(tp, tc) > 0 then
    attached_electro:set_at(tp, tc, 0)
    triggered = true
  end

  if not triggered then return end

  ctx.element = Element.None
  active:sub(1)
  defer_fn(function()
    deal_damage(Target.EnemyAll, Element.Ice, 1, { source = Source.Reaction })
  end)
end)
