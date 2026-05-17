local attached_fire    = get_counter("火元素附着",    Scope.PerChar)
local attached_water   = get_counter("水元素附着",   Scope.PerChar)
local attached_ice     = get_counter("冰元素附着",     Scope.PerChar)
local 雷元素附着 = get_counter("雷元素附着", Scope.PerChar)
local 结晶护盾 = declare_counter("结晶护盾", Scope.PerPlayer, 0, { min = 0, max = 10, tag = Tag.Shield })

local R_CRYSTALLIZE = declare_reaction("Crystallize")  -- ADR-0019 §B.3

on_reaction_damage(function(ctx)
  if ctx.element ~= Element.Geo then return end
  local tp, tc = ctx.target_player, ctx.target_char

  if attached_fire:get_at(tp, tc) <= 0
     and attached_water:get_at(tp, tc) <= 0
     and attached_ice:get_at(tp, tc) <= 0
     and 雷元素附着:get_at(tp, tc) <= 0 then
    return
  end

  attached_fire:set_at(tp, tc, 0)
  attached_water:set_at(tp, tc, 0)
  attached_ice:set_at(tp, tc, 0)
  雷元素附着:set_at(tp, tc, 0)
  ctx.element = Element.None
  set_reaction_kind(R_CRYSTALLIZE)

  local actor = ctx.actor_player
  defer_fn(function()
    结晶护盾:add_at(actor, 1)
  end)
end)

on_shield_absorb(function(ctx)
  local shield = 结晶护盾:get_at(ctx.target_player)
  if shield <= 0 then return end
  local absorb = min(shield, ctx.value)
  结晶护盾:sub_at(ctx.target_player, absorb)
  ctx.value = ctx.value - absorb
end)
