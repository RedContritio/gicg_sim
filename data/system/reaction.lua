local attached_fire    = get_counter("attached_fire",    Scope.PerChar)
local attached_water   = get_counter("attached_water",   Scope.PerChar)
local attached_ice     = get_counter("attached_ice",     Scope.PerChar)
local attached_electro = get_counter("attached_electro", Scope.PerChar)

on_reaction_damage(-10, function(ctx)
  local elem = ctx.element
  if elem == Element.None or elem == Element.Physical or elem == Element.Geo then return end

  local tp, tc = ctx.target_player, ctx.target_char
  if attached_fire:get_at(tp, tc) > 0
     or attached_water:get_at(tp, tc) > 0
     or attached_ice:get_at(tp, tc) > 0
     or attached_electro:get_at(tp, tc) > 0 then
    return
  end

  if     elem == Element.Fire    then attached_fire:set_at(tp, tc, 1)
  elseif elem == Element.Water   then attached_water:set_at(tp, tc, 1)
  elseif elem == Element.Ice     then attached_ice:set_at(tp, tc, 1)
  elseif elem == Element.Electro then attached_electro:set_at(tp, tc, 1)
  end
end)
