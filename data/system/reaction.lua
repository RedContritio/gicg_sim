local attached_fire    = get_counter("火元素附着",    Scope.PerChar)
local attached_water   = get_counter("水元素附着",   Scope.PerChar)
local attached_ice     = get_counter("冰元素附着",     Scope.PerChar)
local 雷元素附着 = get_counter("雷元素附着", Scope.PerChar)

on_reaction_damage(-10, function(ctx)
  local elem = ctx.element
  if elem == Element.None or elem == Element.Physical or elem == Element.Geo then return end

  local tp, tc = ctx.target_player, ctx.target_char
  if attached_fire:get_at(tp, tc) > 0
     or attached_water:get_at(tp, tc) > 0
     or attached_ice:get_at(tp, tc) > 0
     or 雷元素附着:get_at(tp, tc) > 0 then
    return
  end

  if     elem == Element.Fire    then attached_fire:set_at(tp, tc, 1)
  elseif elem == Element.Water   then attached_water:set_at(tp, tc, 1)
  elseif elem == Element.Ice     then attached_ice:set_at(tp, tc, 1)
  elseif elem == Element.Electro then 雷元素附着:set_at(tp, tc, 1)
  end
end)
