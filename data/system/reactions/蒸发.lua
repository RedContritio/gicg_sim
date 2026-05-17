local attached_water = get_counter("水元素附着", Scope.PerChar)
local attached_fire  = get_counter("火元素附着",  Scope.PerChar)

local R_VAPORIZE = declare_reaction("Vaporize")  -- ADR-0019 §B.3

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char
  if ctx.element == Element.Fire and attached_water:get_at(tp, tc) > 0 then
    attached_water:set_at(tp, tc, 0)
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    set_reaction_kind(R_VAPORIZE)
  elseif ctx.element == Element.Water and attached_fire:get_at(tp, tc) > 0 then
    attached_fire:set_at(tp, tc, 0)
    ctx.value = ctx.value + 2
    ctx.element = Element.None
    set_reaction_kind(R_VAPORIZE)
  end
end)
