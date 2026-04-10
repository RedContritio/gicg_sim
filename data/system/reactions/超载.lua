local attached_electro = get_counter("attached_electro", Scope.PerChar)
local attached_fire    = get_counter("attached_fire",    Scope.PerChar)

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  local triggered = false

  if ctx.element == Element.Fire and attached_electro:get_at(tp, tc) > 0 then
    attached_electro:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Electro and attached_fire:get_at(tp, tc) > 0 then
    attached_fire:set_at(tp, tc, 0)
    triggered = true
  end

  if triggered then
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    defer_fn(function() force_switch_next(tp) end)
  end
end)
