local attached_ice   = get_counter("冰元素附着",   Scope.PerChar)
local attached_water = get_counter("水元素附着", Scope.PerChar)
local frozen         = get_counter("冻结",         Scope.PerChar)

local R_FROZEN = declare_reaction("Frozen")  -- ADR-0019 §B.3

on_reaction_damage(function(ctx)
  local tp, tc = ctx.target_player, ctx.target_char

  if ctx.element == Element.Water and attached_ice:get_at(tp, tc) > 0 then
    attached_ice:set_at(tp, tc, 0)
    ctx.element = Element.None
    frozen:set_at(tp, tc, 1)
    set_reaction_kind(R_FROZEN)
  elseif ctx.element == Element.Ice and attached_water:get_at(tp, tc) > 0 then
    attached_water:set_at(tp, tc, 0)
    ctx.element = Element.None
    frozen:set_at(tp, tc, 1)
    set_reaction_kind(R_FROZEN)
  end
end)
