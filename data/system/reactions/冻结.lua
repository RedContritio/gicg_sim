local attached_ice   = get_counter("attached_ice",   Scope.PerChar)
local attached_water = get_counter("attached_water", Scope.PerChar)
local frozen         = get_counter("frozen",         Scope.PerChar)

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char

  if ctx.element == Element.Water and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    ctx.element = Element.None
    frozen:set_at(tp, tc, 1)
  elseif ctx.element == Element.Ice and attached_water:get_at(tp, tc) > 0 then
    attached_water:set_at(tp, tc, 0)
    ctx.element = Element.None
    frozen:set_at(tp, tc, 1)
  end
end)
