local attached_fire    = get_counter("attached_fire",    Scope.PerChar)
local attached_water   = get_counter("attached_water",   Scope.PerChar)
local attached_ice     = get_counter("attached_ice",     Scope.PerChar)
local attached_electro = get_counter("attached_electro", Scope.PerChar)
local 结晶护盾 = declare_counter("结晶护盾", Scope.PerPlayer, 0, { min = 0, max = 10, tag = Tag.Shield })

on_reaction_damage(function(ctx)
  if ctx.element ~= Element.Geo then return end
  local tp, tc = ctx.target_player, ctx.target_char

  if attached_fire:get_at(tp, tc) <= 0
     and attached_water:get_at(tp, tc) <= 0
     and attached_ice:get_at(tp, tc) <= 0
     and attached_electro:get_at(tp, tc) <= 0 then
    return
  end

  attached_fire:set_at(tp, tc, 0)
  attached_water:set_at(tp, tc, 0)
  attached_ice:set_at(tp, tc, 0)
  attached_electro:set_at(tp, tc, 0)
  ctx.element = Element.None

  local actor = ctx.actor_player
  defer_fn(function()
    结晶护盾:add_at(actor, 1)
  end)
end)

on_damage_reduce(function(ctx)
  local shield = 结晶护盾:get_at(ctx.target_player)
  if shield <= 0 then return end
  local absorb = min(shield, ctx.value)
  结晶护盾:sub_at(ctx.target_player, absorb)
  ctx.value = ctx.value - absorb
end)
