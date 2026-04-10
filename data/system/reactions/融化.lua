local attached_ice  = get_counter("attached_ice",  Scope.PerChar)
local attached_fire = get_counter("attached_fire",  Scope.PerChar)

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  if ctx.element == Element.Fire and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    ctx.value = ctx.value + 2
    ctx.element = Element.None
  elseif ctx.element == Element.Ice and attached_fire:get_at(tp, tc) > 0 then
    attached_fire:set_at(tp, tc, 0)
    ctx.value = ctx.value + 2
    ctx.element = Element.None
  end
end)
