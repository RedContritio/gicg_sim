local attached_ice  = get_counter("冰元素附着",  Scope.PerChar)
local attached_fire = get_counter("火元素附着",  Scope.PerChar)

local R_MELT = declare_reaction("Melt")  -- ADR-0019 §B.3

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  if ctx.element == Element.Fire and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    set_reaction_kind(R_MELT)
  elseif ctx.element == Element.Ice and attached_fire:get_at(tp, tc) > 0 then
    attached_fire:set_at(tp, tc, 0)
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    set_reaction_kind(R_MELT)
  end
end)
