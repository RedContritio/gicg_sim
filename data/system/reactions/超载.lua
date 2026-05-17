local 雷元素附着 = get_counter("雷元素附着", Scope.PerChar)
local attached_fire    = get_counter("火元素附着",    Scope.PerChar)

local R_OVERLOAD = declare_reaction("Overload")  -- ADR-0019 §B.3

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  local triggered = false

  if ctx.element == Element.Fire and 雷元素附着:get_at(tp, tc) > 0 then
    雷元素附着:set_at(tp, tc, 0)
    triggered = true
  elseif ctx.element == Element.Electro and attached_fire:get_at(tp, tc) > 0 then
    attached_fire:set_at(tp, tc, 0)
    triggered = true
  end

  if triggered then
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    set_reaction_kind(R_OVERLOAD)
    defer_fn(function() force_switch(tp) end)
  end
end)
